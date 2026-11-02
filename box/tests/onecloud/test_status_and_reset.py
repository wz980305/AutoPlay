"""The status model (docs/STATUS-MODEL.md), the settings page's banners from it, its Host check and its
factory-reset page."""
import json
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
        self.assertIn("重启盒子 / 查看诊断", html)
        self.assertNotIn("数据线", html)
        self.assertIn("蓝牙还没就绪", html)
        self.status.set("bluetooth", "on")
        html = self.page.render("")
        self.assertNotIn("蓝牙没有启动", html)
        self.assertNotIn("蓝牙还没就绪", html)

    def test_certificate_bars(self):
        self.status.update(own_name="mycar.duckdns.org")
        self.status.set("certificate", "expiring_soon", None, not_after="2026-11-20")
        self.status.set("uplink", "offline")
        html = self.page.render("")
        self.assertIn("正式证书将于 2026-11-20 到期", html)
        self.assertIn("插上能上网的 SIM 卡", html)
        self.status.set("certificate", "expired", None, not_after="2026-10-01")
        self.status.set("uplink", "online")
        html = self.page.render("")
        self.assertIn("已于 2026-10-01 过期", html)
        self.assertIn("联网后会自动续签", html)
        self.status.set("certificate", "ok", None, not_after="2027-01-01")
        self.assertNotIn("过期", self.page.render(""))

    def test_the_sound_cell_follows_the_audio_route(self):
        # 1.1.0 (ADR-14): the supervisor publishes uci audio_route_navigation; the page says what navigation does.
        self.assertNotIn("导航播报", self.page.render(""), "nothing until the supervisor says which route is on")
        self.status.update(audio_route="bluetooth")
        html = self.page.render("")
        self.assertIn("走特斯拉蓝牙", html)
        self.assertIn("CarPlay 页面无声", html)
        self.status.update(audio_route="carplay")
        html = self.page.render("")
        self.assertIn("在 CarPlay 页面", html)
        self.assertIn("轻点页面一次开启声音", html)
        self.assertNotIn("页面无声", html)

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
        self.assertNotIn("我的 iPhone", html, "the question is the whole screen")
        # second press carries the confirmation
        reply = self.page.apply("/pair", {"nonce": nonce, "action": "remove", "phone": "02:00:00:00:00:01", "confirmed": "1"})
        self.assertIn("已从盒子上删除", reply)
        self.assertEqual(removed, ["02:00:00:00:00:01"])
        # a phone that is gone: no question, the normal page
        self.page.pairing.devices = lambda: {}
        self.assertIn("我的 iPhone", self.page.render("ask=remove&phone=02%3A00%3A00%3A00%3A00%3A01"))

    def test_an_update_is_confirmed_on_the_page_too(self):
        nonce = self.page.pairing.nonce
        reply = self.page.apply("/update", {"nonce": nonce, "action": "install"})
        self.assertEqual(reply, {"ask": "install"})
        (self.state / "update-check.json").write_text(json.dumps({"available": True, "online": True, "latest": "1.3.0", "current": "1.2.0", "checked_at": 1}))
        html = self.page.render("ask=install")
        self.assertIn("现在升级到 1.3.0？", html)
        self.assertIn("立即升级", html)
        self.assertNotIn("confirm(", html)
        with patch("settings_page.update.launch", return_value="正在升级") as launch:
            self.assertEqual(self.page.apply("/update", {"nonce": nonce, "action": "install", "confirmed": "1"}), "正在升级")
        launch.assert_called_once()
        # nothing to install (offline or none found): the normal page instead of an empty question
        (self.state / "update-check.json").write_text(json.dumps({"available": False, "latest": "1.2.0", "checked_at": 1}))
        self.assertIn("我的 iPhone", self.page.render("ask=install"))


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
