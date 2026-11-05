"""The status model (docs/STATUS-MODEL.md), the settings page's banners from it, its Host check and its
factory-reset page."""
import json
import urllib.parse
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import factory_reset
from settings_page import SettingsPage, host_allowed
from status_model import Status, DOMAINS, read


class StatusModelTests(unittest.TestCase):
    def test_nine_domains_with_state_reason_since(self):
        clock = [1000]
        status = Status(clock=lambda: clock[0], mode="openwrt")
        self.assertEqual(set(DOMAINS), {"bluetooth", "wifi", "uplink", "identity", "phone", "certificate", "update", "system", "tesla"})
        snapshot = status.snapshot()
        for name in DOMAINS:
            self.assertEqual(snapshot[name], {"state": "unknown", "reason": None, "since": 1000})
        self.assertEqual(snapshot["mode"], "openwrt")
        clock[0] = 1010
        self.assertTrue(status.set("bluetooth", "starting", "powering", retry_in=10))
        self.assertEqual(status.domain("bluetooth"), {"state": "starting", "reason": "powering", "since": 1010, "retry_in": 10})
        clock[0] = 1020
        self.assertTrue(status.set("bluetooth", "starting", "powering", retry_in=20), "an extra changed")
        clock[0] = 1030
        self.assertFalse(status.set("bluetooth", "starting", "powering", retry_in=20), "nothing changed: since stays")
        self.assertEqual(status.domain("bluetooth")["since"], 1010, 'telemetry changes do not reset state age')
        with self.assertRaises(KeyError):
            status.set("receiver", "on")

    def test_flat_keys_and_the_file_written_on_change_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            status = Status(path, clock=lambda: 5, home="http://x/")
            status.write()
            first = path.stat().st_mtime_ns
            status["warning"] = "w"
            self.assertEqual(status.get("warning"), "w")
            self.assertIn("warning", status)
            time.sleep(0.01)
            status["warning"] = "w"
            self.assertEqual(json.loads(path.read_text())["warning"], "w")
            after = path.stat().st_mtime_ns
            status.update(warning="w")
            self.assertEqual(path.stat().st_mtime_ns, after, "same content: no write")
            status.pop("warning")
            self.assertNotIn("warning", read(path))
            self.assertEqual(read(path)["bluetooth"]["state"], "unknown")
            self.assertEqual(read(path / "missing"), {})

    def test_failed_publication_can_be_retried(self):
        import status_model
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'status.json'
            status = Status(path)
            with patch.object(status_model.state_files, 'save_json', side_effect=OSError('full')):
                status.set('system', 'ok')
            self.assertFalse(path.exists())
            status.write()
            self.assertEqual(read(path)['system']['state'], 'ok')

    def test_concurrent_publications_cannot_leave_an_older_snapshot(self):
        import status_model
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'status.json'
            status = Status(path)
            entered, release = threading.Event(), threading.Event()
            original = status_model.state_files.save_json
            calls = []
            def save(target, body, **kwargs):
                calls.append(body['system']['state'])
                if len(calls) == 1:
                    entered.set()
                    release.wait(2)
                original(target, body, **kwargs)
            with patch.object(status_model.state_files, 'save_json', side_effect=save):
                old = threading.Thread(target=lambda: status.set('system', 'starting'))
                old.start()
                self.assertTrue(entered.wait(2))
                new = threading.Thread(target=lambda: status.set('system', 'ok'))
                new.start()
                release.set()
                old.join(2); new.join(2)
            self.assertFalse(old.is_alive() or new.is_alive())
            self.assertEqual(read(path)['system']['state'], 'ok')

    def test_removed_metadata_is_not_kept_in_the_published_state(self):
        status = Status()
        status.set('bluetooth', 'starting', 'powering', retry_in=20)
        status.set('bluetooth', 'starting', 'powering')
        self.assertNotIn('retry_in', status.domain('bluetooth'))


class PageBannerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"; self.state.mkdir()
        self.status = Status(clock=lambda: 1, mode="openwrt", ssid="Car-5G", home="http://100.96.0.1:18080/",
                             identity=True, entries=["https://autoplay.lan:18443/"], name="autoplay.lan")
        self.page = SettingsPage(self.state, self.status.snapshot, lambda reason: None, lambda: [])

    def test_bluetooth_failure_is_a_red_bar_with_the_reason(self):
        self.status.set("bluetooth", "failed", "controller-init-failed", retry_in=60)
        html = self.page.render("")
        self.assertIn("蓝牙没有启动：蓝牙芯片初始化失败", html)
        self.assertIn("可以重启盒子；仍不行请下载诊断记录", html)
        self.assertNotIn("数据线", html)
        self.assertIn("蓝牙就绪后才能添加", html)
        self.status.set("bluetooth", "on")
        html = self.page.render("")
        self.assertNotIn("蓝牙没有启动", html)
        self.assertNotIn("蓝牙就绪后才能添加", html)

    def test_certificate_bars(self):
        self.status.update(own_name="mycar.duckdns.org")
        self.status.set("certificate", "expiring_soon", None, not_after="2026-11-20")
        self.status.set("uplink", "offline")
        html = self.page.render("")
        self.assertIn("证书 2026-11-20 到期", html)
        self.assertIn("插上能上网的 SIM 卡", html)
        self.status.set("certificate", "expired", None, not_after="2026-10-01")
        self.status.set("uplink", "online")
        html = self.page.render("")
        self.assertIn("已于 2026-10-01 过期", html)
        self.assertIn("联网后会自动续签", html)
        self.status.set("certificate", "ok", None, not_after="2027-01-01")
        self.assertNotIn("过期", self.page.render(""))

    def test_no_sound_group_and_no_online_banner(self):
        # 1.3.0: every sound is on the Tesla's Bluetooth (no audio route to show), and an upstream that is online is
        # no news; only a down upstream gets a banner (certificates cannot renew, the car will not stay on the hotspot).
        self.status.update(audio_route="carplay", tesla_upstream="online", tesla_internet="上游在线；特斯拉自带音乐、地图可以上网。")
        html = self.page.render("")
        for text in ("导航播报", "声音", "上游在线", "可以上网"):
            self.assertNotIn(text, html)
        self.status.update(tesla_upstream="offline", tesla_internet="上游不可用（没有 4G 信号）；局域网 CarPlay 正常；特斯拉自带音乐、地图不能上网。")
        self.assertIn("盒子没有网络（没有 4G 信号）", self.page.render(""))
        self.status.update(tesla_upstream="unknown", tesla_internet="上游状态检测中；局域网 CarPlay 正常。")
        self.assertNotIn("检测中", self.page.render(""))

    def test_results_are_said_in_their_group_and_errors_at_the_top(self):
        # 1.4.1: a banner at the top is for states to act on and for errors; what an action did is the footer of the
        # group it happened in, and an invitation's note replaces the iPhone group's usual line for that load.
        self.page.pairing.devices = lambda: {"02:00:00:00:00:01": "小王的 iPhone"}
        nonce = self.page.pairing.nonce
        self.page.pairing.use = lambda phone: None
        reply = self.page.apply("/pair", {"nonce": nonce, "action": "use", "phone": "02:00:00:00:00:01"})
        self.assertEqual(reply["at"], "phones")
        html = self.page.render(urllib.parse.urlencode(reply))
        self.assertIn(f'<p class=foot>{reply["m"]}</p>', html)
        self.assertNotIn('class="banner', html)
        self.assertNotIn("添加 iPhone 时，请在车机", html, "the note replaces the usual line once")
        self.assertIn("添加 iPhone 时，请在车机", self.page.render(""))
        self.page.pairing.stop = lambda: None
        self.assertEqual(self.page.apply("/pair", {"nonce": nonce, "action": "cancel"}), "")
        html = self.page.render(urllib.parse.urlencode({"m": "错误：页面已过期，请刷新后重试。", "at": "phones"}))
        self.assertIn('class="banner bad span"', html)
        self.assertIn("页面已过期", html)

    def test_rows_carry_icons_and_no_lines_under_links(self):
        html = self.page.render("")
        for icon in ('class="tile blue"', 'class="tile gray"', 'class="tile green"'):
            self.assertIn(icon, html)
        for gone in ("Wi-Fi 名称、密码或信道改了以后", "画面卡顿、断线时", "我的 iPhone"):
            self.assertNotIn(gone, html.replace("\u2011", "-"))

    def test_wifi_keeps_its_hyphen_in_text_but_fields_keep_what_they_hold(self):
        import settings_ui as ui
        html = ui.keep_words('<p>连上 Wi-Fi 后</p><input name=ssid value="My Wi-Fi"><span title="Wi-Fi">Wi-Fi</span>')
        self.assertEqual(html, '<p>连上 Wi\u2011Fi 后</p><input name=ssid value="My Wi-Fi">'
                               '<span title="Wi-Fi">Wi\u2011Fi</span>')
        self.assertEqual(ui.url("https://car.example.com:18443/"), "https://car.example.com<wbr>:18443/")
        self.assertEqual(ui.url("https://a.example/?x=<1>"), "https://a.example/?x=&lt;1&gt;")

    def test_pairing_lost_tells_the_owner_to_re_add(self):
        self.status.set("phone", "pairing-lost", "pairing-lost")
        self.assertIn("请删除此 iPhone 后重新添加", self.page.render(""))

    def test_box_node_follows_bluetooth_and_receiver(self):
        self.status.set("bluetooth", "failed", "rfkill")
        self.assertIn("蓝牙没有启动</div>", self.page.render(""))
        self.status.set("bluetooth", "on")
        self.status.set("system", "degraded", "receiver-exit-1")
        self.assertIn("程序反复重启", self.page.render(""))
        self.status.set("system", "ok")
        self.assertIn(">运行中<", self.page.render(""))

    def test_no_credentials_and_a_status_endpoint_exist(self):
        self.status.set("identity", "missing", "files-missing")
        html = self.page.render("")
        self.assertIn("还缺 CarPlay 认证文件", html)
        self.assertNotIn("1234", html)
        self.assertIn("恢复出厂设置", html)

    def test_removing_a_phone_is_confirmed_on_the_page_not_in_a_browser_box(self):
        """1.2.0: a car browser draws confirm() at the OS size or not at all, so the question is a screen of the page."""
        self.page.pairing.devices = lambda: {"02:00:00:00:00:01": "小王的 iPhone"}
        removed = []
        self.page.pairing.remove = removed.append
        nonce = self.page.pairing.nonce
        self.assertNotIn("confirm(", self.page.render(""))
        self.assertIn("删除此 iPhone…", self.page.render(""))
        # first press: nothing removed, the redirect asks for the confirmation screen
        reply = self.page.apply("/pair", {"nonce": nonce, "action": "remove", "phone": "02:00:00:00:00:01"})
        self.assertEqual(reply, {"ask": "remove", "phone": "02:00:00:00:00:01"})
        self.assertEqual(removed, [])
        html = self.page.render("ask=remove&phone=02%3A00%3A00%3A00%3A00%3A01")
        self.assertIn("从盒子上删除这部 iPhone？", html)
        self.assertIn("小王的 iPhone", html)
        self.assertIn('name=confirmed value="1"', html)
        self.assertNotIn("添加 iPhone", html, "the question is the whole screen")
        # second press carries the confirmation; the phone leaving the list says it all (no banner, 1.4.1)
        reply = self.page.apply("/pair", {"nonce": nonce, "action": "remove", "phone": "02:00:00:00:00:01", "confirmed": "1"})
        self.assertEqual(reply, "")
        self.assertEqual(removed, ["02:00:00:00:00:01"])
        # a phone that is gone: no question, the normal page
        self.page.pairing.devices = lambda: {}
        self.assertIn("添加 iPhone", self.page.render("ask=remove&phone=02%3A00%3A00%3A00%3A00%3A01"))

    def test_an_update_is_confirmed_on_the_page_too(self):
        nonce = self.page.pairing.nonce
        reply = self.page.apply("/update", {"nonce": nonce, "action": "install"})
        self.assertEqual(reply, {"ask": "install"})
        (self.state / "update-check.json").write_text(json.dumps({"available": True, "online": True, "latest": "1.4.0", "current": "1.3.0", "checked_at": 1}))
        html = self.page.render("ask=install")
        self.assertIn("现在升级到 1.4.0？", html)
        self.assertIn("立即升级", html)
        self.assertNotIn("confirm(", html)
        with patch("settings_page.update.launch", return_value="正在升级，请稍候") as launch:
            self.assertEqual(self.page.apply("/update", {"nonce": nonce, "action": "install", "confirmed": "1"}),
                             {"m": "正在升级，请稍候", "at": "update"})
        launch.assert_called_once()
        # nothing to install (offline or none found): the normal page instead of an empty question
        (self.state / "update-check.json").write_text(json.dumps({"available": False, "latest": "1.3.0", "checked_at": 1}))
        self.assertIn("添加 iPhone", self.page.render("ask=install"))


    def test_the_page_demands_the_typed_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "state").mkdir()
            changes = []
            page = SettingsPage(root / "state", lambda: {"mode": "openwrt", "home": "http://x/"}, changes.append, lambda: [], root=root)
            nonce = page.pairing.nonce
            with self.assertRaises(ValueError):
                page.apply("/reset", {"nonce": nonce, "confirm": "yes"})
            (root / "state/receiver").mkdir(); (root / "state/receiver/browser-token").write_text("t")
            page.uci = lambda *a, **k: None
            with patch.object(page.pairing, "reset_all"), patch("settings_page.threading.Timer") as timer:
                message = page.apply("/reset", {"nonce": nonce, "confirm": "重置"})
            self.assertIn("已重置", message)
            self.assertFalse((root / "state/receiver").exists())
            timer.assert_called_once()
            html = page.render_reset()
            self.assertIn("恢复出厂设置", html)
            self.assertIn("删除认证文件", html)


class HostCheckTests(unittest.TestCase):
    def test_only_the_boxs_own_names_and_addresses(self):
        import ipaddress
        nets = [ipaddress.ip_network("100.96.0.0/24")]
        names = ("mycar.duckdns.org", "autoplay.lan")
        for host in ("100.96.0.1:18080", "100.96.0.1", "autoplay.lan:18080", "MyCar.duckdns.org", "127.0.0.1:18080", "dashplay.lan"):
            self.assertTrue(host_allowed(host, nets, names), host)
        self.assertTrue(host_allowed("[::1]:18080", nets, names), "the IPv6 loopback is the box itself")
        for host in ("evil.example", "10.0.0.1:18080", "192.168.1.1", "", "[fd00::1]:18080"):
            self.assertFalse(host_allowed(host, nets, names), host)


if __name__ == "__main__":
    unittest.main()
