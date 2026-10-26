"""Own DuckDNS name with a Let's Encrypt certificate (own_domain.py): the one route a Tesla's browser is known to open
without a warning. acme.sh is replaced by a script that hands out a synthetic certificate."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/onecloud"))
import boxnet
import own_domain
from settings_page import SettingsPage
import supervisor_openwrt

TOKEN = "0a1b2c3d-1111-2222-3333-444455556666"
FAKE_ACME = """#!/bin/sh
# Records how it was called; --install-cert copies the prepared certificate to the requested files.
echo "$*" >> "$FAKE_DIR/calls"
[ -n "$DuckDNS_Token" ] && echo "token in environment" >> "$FAKE_DIR/calls"
case " $* " in *" --issue "*) [ -n "$FAKE_SLEEP" ] && sleep "$FAKE_SLEEP"; exit "${FAKE_ISSUE:-0}" ;; esac
while [ $# -gt 0 ]; do
    case "$1" in --fullchain-file) cp "$FAKE_DIR/fullchain.pem" "$2" ;; --key-file) cp "$FAKE_DIR/key.pem" "$2" ;; esac
    shift
done
"""


def make_certificate(directory, name, days=90):
    run = lambda *a: subprocess.run(["openssl", *a], check=True, capture_output=True, cwd=directory)
    run("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", "ca.key",
        "-out", "ca.crt", "-days", "100", "-subj", "/CN=Synthetic CA")
    run("req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", "key.pem",
        "-out", "leaf.csr", "-subj", "/CN=" + name)
    (Path(directory) / "ext").write_text(f"subjectAltName=DNS:{name}\n")
    run("x509", "-req", "-in", "leaf.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-days", str(days),
        "-extfile", "ext", "-out", "leaf.crt")
    (Path(directory) / "fullchain.pem").write_text((Path(directory) / "leaf.crt").read_text()
                                                   + (Path(directory) / "ca.crt").read_text())


class ConfigTests(unittest.TestCase):
    def test_sub_domain_accepts_the_full_name_and_capitals(self):
        self.assertEqual(own_domain.sub_domain(" MyCar.duckdns.org "), "mycar")
        for bad in ("", "my car", "-x", "a.b", "x" * 64):
            with self.assertRaises(ValueError):
                own_domain.sub_domain(bad)
        with self.assertRaises(ValueError):
            own_domain.check_token("short")

    def test_openwrt_reads_it_from_uci_and_ignores_a_bad_one(self):
        base = supervisor_openwrt.read_config("dashplay.main.duckdns_domain='MyCar'\n"
                                              f"dashplay.main.duckdns_token='{TOKEN}'\n")
        self.assertEqual(supervisor_openwrt.own_config(base), {"domain": "mycar", "token": TOKEN})
        self.assertIsNone(supervisor_openwrt.own_config(supervisor_openwrt.read_config("")))
        bad = supervisor_openwrt.read_config("dashplay.main.duckdns_domain='mycar'\ndashplay.main.duckdns_token='x'\n")
        self.assertIsNone(supervisor_openwrt.own_config(bad), "a wrong token turns it off, CarPlay still starts")


@unittest.skipUnless(shutil.which("openssl"), "needs the openssl command")
class MaintainerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "dashplay"; self.state = self.root / "state"
        (self.root / "acme").mkdir(parents=True); self.state.mkdir()
        self.fake = Path(tmp.name) / "fake"; self.fake.mkdir()
        acme = self.root / "acme" / "acme.sh"
        acme.write_text(FAKE_ACME); acme.chmod(0o755)
        self.config = {"domain": "mycar", "token": TOKEN}
        self.name = "mycar.duckdns.org"
        env = patch.dict(os.environ, FAKE_DIR=str(self.fake)); env.start(); self.addCleanup(env.stop)
        self.records = []
        record = patch.object(own_domain, "update_record", lambda config, address: self.records.append(address) or True)
        record.start(); self.addCleanup(record.stop)
        self.stopped = threading.Event()

    def maintainer(self, address="192.168.5.80"):
        return own_domain.Maintainer(self.root, self.config, address, self.stopped, say=lambda _: None)

    def calls(self):
        return (self.fake / "calls").read_text()

    def test_obtains_installs_and_serves_the_certificate(self):
        make_certificate(self.fake, self.name)
        self.assertEqual(self.maintainer().check_certificate(), own_domain.CERT_CHECK)
        own = self.state / "tls" / "own"
        self.assertTrue(own_domain.certificate_for(self.state, self.name, own_domain.RENEW_DAYS))
        self.assertEqual((own / "key.pem").stat().st_mode & 0o777, 0o600)
        self.assertEqual(own_domain.read_status(self.state)["phase"], "ready")
        self.assertIn("--dns dns_duckdns", self.calls())
        self.assertIn("token in environment", self.calls())
        self.assertNotIn(TOKEN, self.calls(), "the token stays off acme.sh's command line")
        self.assertIn("下次开机时启用", own_domain.message(self.state, self.name))
        boxnet.ensure_keystore(self.state)   # the next start
        self.assertTrue(own_domain.serving(self.state))
        self.assertNotIn("下次开机", own_domain.message(self.state, self.name))

    def test_a_current_certificate_is_left_alone(self):
        make_certificate(self.fake, self.name)
        self.maintainer().check_certificate()
        (self.fake / "calls").unlink()
        self.assertEqual(self.maintainer().check_certificate(), own_domain.CERT_CHECK)
        self.assertFalse((self.fake / "calls").exists(), "acme.sh not run while more than 30 days remain")

    def test_a_certificate_for_another_name_is_refused(self):
        make_certificate(self.fake, "someone-else.duckdns.org")
        self.assertEqual(self.maintainer().check_certificate(), own_domain.CERT_RETRIES[0])
        self.assertFalse((self.state / "tls" / "own" / "fullchain.pem").exists())
        self.assertEqual(own_domain.read_status(self.state)["phase"], "retry")
        self.assertIn("每小时重试", own_domain.message(self.state, self.name))

    def test_failure_is_retried_with_back_off_then_hourly(self):
        # reliability_audit #6: one try at start, then hourly, never renewed on drives shorter than an hour.
        worker = self.maintainer()
        with patch.dict(os.environ, FAKE_ISSUE="1"):
            delays = [worker.check_certificate() for _ in range(6)]
        self.assertEqual(delays, [60, 120, 300, 900, 3600, 3600])
        status = own_domain.read_status(self.state)
        self.assertEqual((status["phase"], status["failures"]), ("retry", 6))
        self.assertEqual(own_domain.certificate_state(self.state, self.name)["state"], "failed")
        make_certificate(self.fake, self.name)
        self.assertEqual(worker.check_certificate(), own_domain.CERT_CHECK)
        self.assertEqual(worker.cert_failures, 0)

    def test_a_network_event_wakes_the_maintainer(self):
        wake = self.root / "wan-up"
        worker = own_domain.Maintainer(self.root, self.config, None, self.stopped, say=lambda _: None, wake_file=wake)
        self.assertFalse(worker.woken())
        wake.write_text("")
        self.assertTrue(worker.woken())
        self.assertFalse(wake.exists(), "consumed")

    def test_certificate_state_for_the_status_model(self):
        self.assertEqual(own_domain.certificate_state(self.state, None)["state"], "self_signed")
        self.assertEqual(own_domain.certificate_state(self.state, self.name)["state"], "issuing")
        make_certificate(self.fake, self.name, days=10)
        own = self.state / "tls" / "own"; own.mkdir(parents=True)
        shutil.copy(self.fake / "fullchain.pem", own); shutil.copy(self.fake / "key.pem", own)
        own_domain.write_status(self.state, name=self.name, phase="ready")
        info = own_domain.certificate_state(self.state, self.name)
        self.assertEqual(info["state"], "expiring_soon")
        self.assertRegex(info["not_after"], r"\d{4}-\d{2}-\d{2}")
        self.assertEqual(own_domain.certificate_state(self.state, self.name, now=time.time() - 60 * 86400)["state"], "ok")
        self.assertEqual(own_domain.certificate_state(self.state, self.name, now=time.time() + 20 * 86400)["state"], "expired")
        own_domain.write_status(self.state, name=self.name, phase="renewing")
        self.assertEqual(own_domain.certificate_state(self.state, self.name)["state"], "renewing")

    def test_stopping_the_service_stops_acme(self):
        make_certificate(self.fake, self.name)
        with patch.dict(os.environ, FAKE_SLEEP="30"):
            worker = self.maintainer(None)
            worker.start()
            time.sleep(1)
            started = time.monotonic()
            self.stopped.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual(self.records, [], "no address: the record is left as it is")

    def test_the_record_follows_the_address(self):
        make_certificate(self.fake, self.name)
        worker = self.maintainer("192.168.78.1")
        worker.start()
        for _ in range(50):
            if self.records:
                break
            time.sleep(0.1)
        self.stopped.set(); worker.join(10)
        self.assertEqual(self.records[:1], ["192.168.78.1"])
        self.assertEqual(own_domain.read_status(self.state)["record"], "ok")






class RecordTests(unittest.TestCase):


    def test_record_query(self):
        urls = []
        class Answer:
            def __init__(self, url): urls.append(url)
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n): return b"OK"
        with patch.object(own_domain.urllib.request, "urlopen", lambda url, timeout: Answer(url)):
            self.assertTrue(own_domain.update_record({"domain": "mycar", "token": TOKEN}, "100.96.0.1"))
        self.assertIn("ip=100.96.0.1", urls[0]); self.assertIn("domains=mycar", urls[0]); self.assertIn(f"token={TOKEN}", urls[0])
        self.assertEqual(len(urls), 1)

    def test_tesla_guard_keeps_the_record_for_an_unreachable_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "state").mkdir()
            worker = own_domain.Maintainer(root, {"domain": "mycar", "token": TOKEN}, "192.168.1.1", threading.Event(),
                                           say=lambda _: None, tesla=True)
            self.assertIsNone(worker.address)
            self.assertEqual(own_domain.read_status(root / "state")["record"], "blocked")
            self.assertIn("已保留原域名记录", own_domain.message(root / "state", "mycar.duckdns.org"))
            worker = own_domain.Maintainer(root, {"domain": "mycar", "token": TOKEN}, "100.96.0.1", threading.Event(),
                                           say=lambda _: None, tesla=True)
            self.assertEqual(worker.address, "100.96.0.1")


class SettingsPageTests(unittest.TestCase):
    def test_the_page_shows_the_name_and_takes_no_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"; state.mkdir()
            status = {"mode": "openwrt", "entries": [], "home": "http://100.96.0.1:18080/", "own_name": "mycar.duckdns.org"}
            page = SettingsPage(state, lambda: status, lambda _: None, lambda: [])
            with self.assertRaises(ValueError):
                page.apply("/ddns", {"action": "save", "domain": "x", "token": TOKEN, "nonce": page.pairing.nonce})
            html = page.render("")
            self.assertIn("mycar.duckdns.org", html)
            self.assertIn("等待申请正式证书", html)
            self.assertNotIn("name=token", html)
            self.assertNotIn("自己的域名", SettingsPage(state, lambda: dict(status, own_name=None), lambda _: None,
                                                lambda: []).render(""))


if __name__ == "__main__":
    unittest.main()
