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
