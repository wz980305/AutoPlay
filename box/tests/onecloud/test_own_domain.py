"""Own DuckDNS name with a Let's Encrypt certificate (own_domain.py): the one route a Tesla's browser is known to open
without a warning. acme.sh is replaced by a script that hands out a synthetic certificate."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
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
DNSPOD_TOKEN = "0123456789abcdef0123456789abcdef"   # synthetic, 32 alphanumerics like a DNSPod API token
FAKE_ACME = """#!/bin/sh
# Records how it was called; --install-cert copies the prepared certificate to the requested files.
echo "$*" >> "$FAKE_DIR/calls"
[ -n "$DuckDNS_Token" ] && echo "token in environment" >> "$FAKE_DIR/calls"
[ -n "$DP_Id" ] && [ -n "$DP_Key" ] && echo "dnspod credentials in environment" >> "$FAKE_DIR/calls"
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
        base = supervisor_openwrt.read_config("autoplay.main.duckdns_domain='MyCar'\n"
                                              f"autoplay.main.duckdns_token='{TOKEN}'\n")
        self.assertEqual(supervisor_openwrt.own_config(base), {"domain": "mycar", "provider": "duckdns", "token": TOKEN})
        self.assertIsNone(supervisor_openwrt.own_config(supervisor_openwrt.read_config("")))
        bad = supervisor_openwrt.read_config("autoplay.main.duckdns_domain='mycar'\nautoplay.main.duckdns_token='x'\n")
        self.assertIsNone(supervisor_openwrt.own_config(bad), "a wrong token turns it off, CarPlay still starts")

    # Tencent Cloud (DNSPod), the second provider (1.0.0) --------------------------------------------

    def test_dnspod_fields_are_checked_and_normalised(self):
        self.assertEqual(own_domain.fqdn(" Car.Example.COM. "), "car.example.com")
        for bad in ("", "car", "car.", ".example.com", "car example.com", "-car.example.com", "x" * 64 + ".com"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                own_domain.fqdn(bad)
        self.assertEqual(own_domain.check_dnspod_id(" 123456 "), "123456")
        for bad in ("", "12", "12a456", "x" * 17):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                own_domain.check_dnspod_id(bad)
        self.assertEqual(own_domain.check_dnspod_token("a" * 32), "a" * 32)
        for bad in ("", "short", "a" * 65, "has-dash-" + "a" * 20):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                own_domain.check_dnspod_token(bad)

    def test_openwrt_reads_the_dnspod_provider_and_ignores_a_bad_one(self):
        good = supervisor_openwrt.read_config("autoplay.main.dns_provider='dnspod'\n"
                                              "autoplay.main.own_domain='Car.Example.com'\n"
                                              "autoplay.main.dnspod_id='123456'\n"
                                              f"autoplay.main.dnspod_token='{DNSPOD_TOKEN}'\n")
        self.assertEqual(supervisor_openwrt.own_config(good),
                         {"domain": "car.example.com", "provider": "dnspod", "id": "123456", "token": DNSPOD_TOKEN})
        # dnspod selected but no domain: off, not an error.
        self.assertIsNone(supervisor_openwrt.own_config(supervisor_openwrt.read_config("autoplay.main.dns_provider='dnspod'\n")))
        # A bad credential turns it off; CarPlay still starts.
        bad = supervisor_openwrt.read_config("autoplay.main.dns_provider='dnspod'\nautoplay.main.own_domain='car.example.com'\n"
                                             "autoplay.main.dnspod_id='12'\nautoplay.main.dnspod_token='x'\n")
        self.assertIsNone(supervisor_openwrt.own_config(bad))
        # A DuckDNS entry does not leak into the dnspod branch, and vice versa.
        mixed = supervisor_openwrt.read_config("autoplay.main.dns_provider='dnspod'\nautoplay.main.duckdns_domain='mycar'\n"
                                               f"autoplay.main.duckdns_token='{TOKEN}'\n")
        self.assertIsNone(supervisor_openwrt.own_config(mixed), "dnspod selected, no own_domain: off")

    def test_the_name_is_the_full_domain_for_dnspod_and_the_duckdns_one_otherwise(self):
        self.assertEqual(own_domain.name_of({"domain": "car.example.com", "provider": "dnspod", "id": "1", "token": "t"}),
                         "car.example.com")
        self.assertEqual(own_domain.name_of({"domain": "mycar", "provider": "duckdns", "token": TOKEN}), "mycar.duckdns.org")
        self.assertEqual(own_domain.name_of({"domain": "mycar", "token": TOKEN}), "mycar.duckdns.org", "pre-1.0.0 config")
        self.assertIsNone(own_domain.name_of(None))
        self.assertEqual(supervisor_openwrt.box_name({"domain": "car.example.com", "provider": "dnspod", "id": "1", "token": "t"}),
                         "car.example.com")

    def test_dnspod_has_no_record_to_update(self):
        with patch.object(own_domain.urllib.request, "urlopen") as network:
            self.assertTrue(own_domain.update_record({"domain": "car.example.com", "provider": "dnspod", "id": "1", "token": "t"},
                                                     "100.96.0.1"))
        network.assert_not_called()


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

    def maintainer(self, address="192.168.5.80", ready=None):
        worker = own_domain.Maintainer(self.root, self.config, address, self.stopped, say=lambda _: None)
        worker.ready = ready or (lambda provider: None)   # the network is there unless a test says otherwise (D1)
        return worker

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

    def test_dnspod_issues_through_the_dns_dp_hook_with_credentials_in_the_environment(self):
        config = {"domain": "car.example.com", "provider": "dnspod", "id": "123456", "token": DNSPOD_TOKEN}
        make_certificate(self.fake, "car.example.com")
        worker = own_domain.Maintainer(self.root, config, "100.96.0.1", self.stopped, say=lambda _: None)
        asked = []
        worker.ready = lambda provider: asked.append(provider)
        self.assertEqual(worker.name, "car.example.com")
        self.assertEqual(worker.check_certificate(), own_domain.CERT_CHECK)
        self.assertTrue(own_domain.certificate_for(self.state, "car.example.com", own_domain.RENEW_DAYS))
        calls = self.calls()
        self.assertIn("--dns dns_dp", calls)
        self.assertIn("-d car.example.com", calls)
        self.assertNotIn("dns_duckdns", calls)
        self.assertIn("dnspod credentials in environment", calls)
        self.assertNotIn("token in environment", calls, "no DuckDNS token is handed to acme.sh for a DNSPod name")
        self.assertNotIn(DNSPOD_TOKEN, calls, "the token stays off acme.sh's command line")
        self.assertNotIn("123456", calls.replace("car.example.com", ""), "the API id stays off the command line")
        self.assertEqual(own_domain.read_status(self.state)["phase"], "ready")
        self.assertEqual(asked, ["dnspod"], "the readiness probe knows which provider to resolve")

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

    def test_no_route_or_dns_yet_is_waiting_not_a_failure(self):
        # D1 (DashPlay 2026.10.26): at boot the first attempt landed before the SIM was up and cost a back-off step.
        for missing in ("route", "dns"):
            with self.subTest(missing=missing):
                worker = self.maintainer(ready=lambda provider, m=missing: m)
                self.assertEqual(worker.check_certificate(), own_domain.READY_RETRY)
                self.assertEqual(worker.cert_failures, 0)
                status = own_domain.read_status(self.state)
                self.assertEqual((status["phase"], status["reason"]), ("waiting", missing))
                self.assertFalse((self.fake / "calls").exists(), "acme.sh is not run while the network is not there")
                self.assertEqual(own_domain.certificate_state(self.state, self.name)["state"], "issuing")
                self.assertEqual(own_domain.certificate_state(self.state, self.name)["reason"], missing)
                self.assertIn(own_domain.reason_text(missing), own_domain.message(self.state, self.name))
        # A probe that itself fails never kills the worker: treated as "route".
        def broken(provider):
            raise OSError("ip went away")
        self.assertEqual(self.maintainer(ready=broken).check_certificate(), own_domain.READY_RETRY)
        self.assertEqual(own_domain.read_status(self.state)["reason"], "route")

    def test_the_failure_reason_is_a_code_from_this_runs_log_never_a_message(self):
        # D3: the settings page gets a word (curl code, timeout, acme); the token in acme.sh's output never leaves the log.
        worker = self.maintainer()
        log = self.state / "acme" / "acme.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("old run: curl: (6) Could not resolve host; error code: 6\n")
        with patch.dict(os.environ, FAKE_ISSUE="1"):
            worker.check_certificate()
        status = own_domain.read_status(self.state)
        self.assertEqual(status["phase"], "retry")
        self.assertEqual(status["reason"], "acme", "obtain() starts a fresh log and the fake acme.sh wrote nothing to it")
        self.assertNotIn(TOKEN, json.dumps(status))
        self.assertIn("acme.sh 申请没有成功", own_domain.message(self.state, self.name))
        log.write_text("curl: (6) Could not resolve host; error code: 6\n")   # what this run's log would say
        self.assertEqual(own_domain.failure_reason(TimeoutError("x")), "timeout")
        self.assertEqual(own_domain.failure_reason(ValueError("x")), "certificate")
        self.assertEqual(own_domain.failure_reason(OSError("x")), "network")
        self.assertEqual(own_domain.failure_reason(RuntimeError("x")), "acme")
        self.assertEqual(own_domain.failure_reason(RuntimeError("x"), log), "curl6", "a log this run wrote names the curl code")
        self.assertIn("curl 错误 6", own_domain.reason_text("curl6"))

    def test_acme_runs_with_a_bounded_curl_in_front_of_its_own(self):
        # D2: acme.sh 3.1.6 has no request timeout; a shim adds --connect-timeout/--max-time/--retry. acme.sh is unchanged.
        make_certificate(self.fake, self.name)
        self.assertEqual(self.maintainer().check_certificate(), own_domain.CERT_CHECK)
        shim = self.state / "acme" / "bin" / "curl"
        self.assertTrue(shim.exists(), "the shim is written beside acme.sh's config home")
        self.assertEqual(shim.stat().st_mode & 0o777, 0o700)
        text = shim.read_text()
        self.assertIn(f"--connect-timeout {own_domain.ACME_CONNECT_TIMEOUT}", text)
        self.assertIn(f"--max-time {own_domain.ACME_REQUEST_TIMEOUT}", text)
        self.assertIn('"$@"', text)
        self.assertEqual(hashlib.sha256((self.root / "acme" / "acme.sh").read_bytes()).hexdigest(),
                         hashlib.sha256(FAKE_ACME.encode()).hexdigest(), "acme.sh itself is byte-identical")

    def test_a_network_event_wakes_the_maintainer(self):
        wake = self.root / "wan-up"
        worker = own_domain.Maintainer(self.root, self.config, None, self.stopped, say=lambda _: None, wake_file=wake)
        self.assertFalse(worker.woken())
        wake.write_text("")
        self.assertTrue(worker.woken())
        self.assertFalse(wake.exists(), "consumed")

    def test_openssl_timeout_retries_instead_of_killing_the_worker(self):
        worker = self.maintainer()
        with patch.object(own_domain, 'certificate_for', side_effect=subprocess.TimeoutExpired('openssl', 30)):
            self.assertEqual(worker.check_certificate(), own_domain.CERT_RETRIES[0])
            self.assertEqual(worker.check_certificate(), own_domain.CERT_RETRIES[1])
        self.assertEqual(own_domain.read_status(self.state)['reason'], 'timeout')   # a code since 1.1.0 (D3), never a message

    def test_full_state_disk_does_not_end_certificate_maintenance(self):
        with patch.object(own_domain, 'save_json', side_effect=OSError('full')):
            own_domain.write_status(self.state, name=self.name, phase='retry')
            with patch.object(own_domain, 'certificate_for', return_value=True):
                self.assertEqual(self.maintainer().check_certificate(), own_domain.CERT_CHECK)

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


class ReadinessTests(unittest.TestCase):
    """has_default_route() reads /proc (BusyBox ip has no JSON); network_ready() resolves the provider and the CA."""

    def proc(self, route="", ipv6=""):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        net = Path(tmp.name) / "net"; net.mkdir()
        (net / "route").write_text("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n" + route)
        (net / "ipv6_route").write_text(ipv6)
        return Path(tmp.name)

    def test_default_route_detection(self):
        up = "wwan0\t00000000\t0A40600A\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
        down = "wwan0\t00000000\t0A40600A\t0002\t0\t0\t0\t00000000\t0\t0\t0\n"
        reject = "lo\t00000000\t00000000\t0203\t0\t0\t0\t00000000\t0\t0\t0\n"
        lan = "br-lan\t00006064\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
        self.assertTrue(own_domain.has_default_route(self.proc(up + lan)))
        self.assertFalse(own_domain.has_default_route(self.proc(lan)), "a LAN route is not a default route")
        self.assertFalse(own_domain.has_default_route(self.proc(down)), "a default route that is not up")
        self.assertFalse(own_domain.has_default_route(self.proc(reject)), "an unreachable default is a reject route")
        v6 = "0" * 32 + " 00 " + "0" * 32 + " 00 " + "fe800000000000000000000000000001" + " 00000400 00000001 00000000 00000003 wwan0\n"
        self.assertTrue(own_domain.has_default_route(self.proc("", v6)), "an IPv6-only uplink counts")
        self.assertFalse(own_domain.has_default_route(self.proc("", v6.replace(" wwan0", " lo"))))
        self.assertFalse(own_domain.has_default_route(Path("/nonexistent")), "no /proc: not ready, never an exception")

    def test_network_ready_names_what_is_missing(self):
        proc = self.proc("wwan0\t00000000\t0A40600A\t0003\t0\t0\t0\t00000000\t0\t0\t0\n")
        asked = []
        def resolve(host, port, type=None):
            asked.append(host)
        self.assertIsNone(own_domain.network_ready("dnspod", resolve=resolve, proc=proc))
        self.assertEqual(asked, ["dnsapi.cn", "acme-v02.api.letsencrypt.org"] if own_domain.ACME_SERVER == "letsencrypt"
                         else ["dnsapi.cn", own_domain.directory_host()])
        asked.clear()
        self.assertIsNone(own_domain.network_ready("duckdns", resolve=resolve, proc=proc))
        self.assertEqual(asked[0], "www.duckdns.org")
        def failing(host, port, type=None):
            raise socket.gaierror("no DNS")
        self.assertEqual(own_domain.network_ready("duckdns", resolve=failing, proc=proc), "dns")
        self.assertEqual(own_domain.network_ready("duckdns", resolve=resolve, proc=self.proc("")), "route")
