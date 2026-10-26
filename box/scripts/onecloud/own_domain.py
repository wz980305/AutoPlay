"""Optional: a DuckDNS name with a Let's Encrypt certificate. The only route verified on a Tesla (F50 2026-10-14):
its browser opens https://<name>.duckdns.org:18443/ without a certificate warning (tesla_only_box_delta.md 0).
Off unless the owner enters a DuckDNS sub-domain and token in LuCI (uci duckdns_domain / duckdns_token).

- The public DuckDNS record points the name at the router's LAN address (100.96.0.1). DuckDNS takes a private
  address; the box's own dnsmasq answers the name locally for the Tesla as well (tesla_openwrt.OfflineChecks).
- The certificate comes from Let's Encrypt through acme.sh (bundled in acme/) with a DNS-01 challenge: only
  outgoing HTTPS, nothing has to reach the box, so it works over the SIM. It is installed in state/tls/own/,
  which boxnet wraps into the receiver's keystore; a new one loads on the next receiver start, never mid-drive.
  Renewed when less than RENEW_DAYS remain, whenever the box is online.
- The token reaches acme.sh by its environment only (not its command line); it is never logged or shown.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from state import tesla_reaches

SUFFIX = ".duckdns.org"
DOMAIN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
TOKEN = re.compile(r"[A-Za-z0-9-]{16,64}")   # DuckDNS shows a UUID
RENEW_DAYS = 30            # Let's Encrypt certificates last 90 days
RECORD_REFRESH = 1800      # seconds between DuckDNS updates once one succeeded
RECORD_RETRY = 60
CERT_CHECK = 12 * 3600
# Retries after a failed issue/renewal: 60 s, 2 min, 5 min, 15 min, then hourly; a WAN-up or NTP hotplug event
# (the supervisor's wake file) tries at once. Daily drives shorter than an hour never renewed before
# (reliability_audit #6).
CERT_RETRIES = (60, 120, 300, 900)
CERT_RETRY = 3600
ACME_TIMEOUT = 600
DNS_SLEEP = 60             # wait for the TXT record instead of acme.sh's DoH check (blocked on some networks)
ACME_SERVER = os.environ.get("DASHPLAY_ACME_SERVER", "letsencrypt")   # tests: letsencrypt_test


def sub_domain(text):
    """'MyCar', 'mycar.duckdns.org' -> 'mycar'; ValueError when not a DuckDNS sub-domain."""
    domain = (text or "").strip().lower().removesuffix(SUFFIX)
    if not DOMAIN.fullmatch(domain):
        raise ValueError("DuckDNS 子域名只能包含小写字母、数字和连字符。")
    return domain


def check_token(token):
    token = (token or "").strip()
    if not TOKEN.fullmatch(token):
        raise ValueError("DuckDNS token 格式不对：在 duckdns.org 登录后页面上方的 token 一栏复制。")
    return token


def name_of(config):
    return config["domain"] + SUFFIX if config else None


def forget_certificate(state):
    """When the name changes or the feature is turned off: the certificate is for the old name."""
    shutil.rmtree(Path(state) / "tls" / "own", ignore_errors=True)
    (Path(state) / "own-domain.json").unlink(missing_ok=True)


def update_record(config, address, timeout=15):
    """Point the name at address (private addresses allowed). True when DuckDNS answered OK."""
    query = urllib.parse.urlencode({"ip": address, "domains": config["domain"], "token": config["token"]})
    with urllib.request.urlopen("https://www.duckdns.org/update?" + query, timeout=timeout) as response:
        return response.read(16).strip() == b"OK"


def _openssl(*args):
    return subprocess.run(["openssl", *args], capture_output=True, text=True, timeout=30)


def certificate_for(state, name, days=0):
    """The installed certificate is for name and stays valid `days` more."""
    chain = Path(state) / "tls" / "own" / "fullchain.pem"
    if not chain.exists():
        return False
    host = _openssl("x509", "-noout", "-checkhost", name, "-in", str(chain))
    return "does match" in host.stdout and _openssl(
        "x509", "-noout", "-checkend", str(days * 86400), "-in", str(chain)).returncode == 0


def end_date(state):
    """'2027-01-11' for the installed certificate, or None."""
    out = _openssl("x509", "-noout", "-enddate", "-in", str(Path(state) / "tls" / "own" / "fullchain.pem"))
    if out.returncode:
        return None
    try:
        return time.strftime("%Y-%m-%d", time.strptime(out.stdout.strip().split("=", 1)[1], "%b %d %H:%M:%S %Y %Z"))
    except (IndexError, ValueError):
        return None


def write_status(state, **fields):
    """Fixed, public fields only (phase, record, address): never an error text, which may carry the token."""
    path = Path(state) / "own-domain.json"
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        old = {}
    value = dict(old if isinstance(old, dict) else {}, **fields)
    fd, temporary = tempfile.mkstemp(prefix=".own-domain.", dir=state)
    with os.fdopen(fd, "w") as out:
        json.dump(value, out)
    Path(temporary).replace(path)


def read_status(state):
    try:
        value = json.loads((Path(state) / "own-domain.json").read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


class Maintainer(threading.Thread):
    """Keeps the DuckDNS record on `address` (None: leave it) and the certificate current, until stopped."""

    def __init__(self, root, config, address, stopped, say=print, tesla=False, wake_file=None):
        super().__init__(name="own-domain", daemon=True)
        self.root, self.state = Path(root), Path(root) / "state"
        self.config, self.name, self.address = config, name_of(config), address
        self.wake_file = Path(wake_file) if wake_file else None
        self.cert_failures = 0
        if tesla and address and not tesla_reaches(address):
            # Cannot happen once the LAN is the install-time constant (D1); kept as a guard for a hand-edited LAN.
            self.address = None
            write_status(self.state, name=self.name, record="blocked", warning="特斯拉无法打开当前地址，已保留原域名记录")
            say("DuckDNS record kept: Tesla cannot reach the current address")
        self.stopped, self.say = stopped, say
        self.sent, self.sent_at = None, 0.0   # address last accepted by DuckDNS, and when

    def woken(self):
        """A hotplug event (WAN up, NTP synced) since the last look: the supervisor's wake file, consumed here."""
        if self.wake_file is None:
            return False
        try:
            self.wake_file.unlink()
            return True
        except OSError:
            return False

    def run(self):
        next_record = next_cert = time.monotonic()
        while not self.stopped.is_set():
            now = time.monotonic()
            if self.woken():
                self.say("own name: network event, retrying now")
                next_record = next_cert = now
            if self.address and now >= next_record:
                if self.address == self.sent and now < self.sent_at + RECORD_REFRESH:
                    ok = True   # nothing changed since DuckDNS took it
                else:
                    try:
                        ok = update_record(self.config, self.address)
                    except (OSError, ValueError):   # no internet yet; URLError is an OSError
                        ok = False
                    if ok:
                        self.sent, self.sent_at = self.address, now
                    self.say(f"duckdns {self.name} -> {self.address}: {'OK' if ok else 'failed'}")
                write_status(self.state, name=self.name, record="ok" if ok else "failed", address=self.address)
                next_record = now + (RECORD_RETRY if not ok else RECORD_REFRESH)
            if now >= next_cert:
                next_cert = now + self.check_certificate()
            if not self.address:
                next_record = float("inf")
            # Wake up every few seconds to see the wake file; the real work waits for its own deadline.
            self.stopped.wait(max(1.0, min(next_record, next_cert, time.monotonic() + 5) - time.monotonic()))

    def retry_delay(self):
        """Back-off of the certificate retries: CERT_RETRIES, then CERT_RETRY."""
        index = self.cert_failures - 1
        return CERT_RETRIES[index] if 0 <= index < len(CERT_RETRIES) else CERT_RETRY

    def check_certificate(self):
        """Seconds until the next look."""
        if certificate_for(self.state, self.name, RENEW_DAYS):
            self.cert_failures = 0
            write_status(self.state, name=self.name, phase="ready")
            return CERT_CHECK
        renewing = certificate_for(self.state, self.name)
        write_status(self.state, name=self.name, phase="renewing" if renewing else "issuing")
        try:
            self.obtain()
        except InterruptedError:
            return CERT_CHECK
        except Exception as error:   # no internet, DuckDNS or Let's Encrypt refused; texts may carry the token
            self.cert_failures += 1
            delay = self.retry_delay()
            write_status(self.state, name=self.name, phase="retry", failures=self.cert_failures,
                         reason=type(error).__name__)
            self.say(f"certificate for {self.name} deferred: {type(error).__name__}; next try in {delay} s")
            return delay
        self.cert_failures = 0
        write_status(self.state, name=self.name, phase="ready")
        self.say(f"certificate for {self.name} installed until {end_date(self.state)}; used from the next start")
        return CERT_CHECK

    def obtain(self):
        home = self.state / "acme"
        home.mkdir(mode=0o700, exist_ok=True)
        log = home / "acme.log"
        log.unlink(missing_ok=True)   # one run's log only (private, 0600)
        # One worker at a time, also across a supervisor restart while acme.sh is still running.
        fd = os.open(home / "dashplay.lock", os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # 2: acme.sh still has a certificate it considers current; install that one.
            if self.acme(["--issue", "--dns", "dns_duckdns", "--dnssleep", str(DNS_SLEEP), "-d", self.name,
                          "--keylength", "ec-256"], log) not in (0, 2):
                raise RuntimeError("acme.sh could not obtain the certificate")
            with tempfile.TemporaryDirectory(dir=home) as scratch:
                chain, key = Path(scratch) / "fullchain.pem", Path(scratch) / "key.pem"
                if self.acme(["--install-cert", "-d", self.name, "--ecc", "--fullchain-file", str(chain),
                              "--key-file", str(key)], log) != 0:
                    raise RuntimeError("acme.sh could not export the certificate")
                self.install(chain, key)

    def install(self, chain, key):
        """Only a certificate for this name whose key matches replaces the installed one."""
        pub = lambda *args: _openssl(*args).stdout
        if "does match" not in pub("x509", "-noout", "-checkhost", self.name, "-in", str(chain)) or (
                pub("x509", "-noout", "-pubkey", "-in", str(chain)) != pub("pkey", "-pubout", "-in", str(key))):
            raise ValueError("certificate does not match")
        own = self.state / "tls" / "own"
        own.mkdir(mode=0o700, parents=True, exist_ok=True)
        key.chmod(0o600)
        key.replace(own / "key.pem")
        chain.replace(own / "fullchain.pem")

    def acme(self, arguments, log):
        """acme.sh in its own process group, cancelled when the service stops; the token only in its environment."""
        home = self.state / "acme"
        command = [str(self.root / "acme" / "acme.sh"), "--home", str(self.root / "acme"), "--config-home", str(home),
                   "--cert-home", str(home / "certs"), *arguments, "--server", ACME_SERVER, "--no-color"]
        env = dict(os.environ, DuckDNS_Token=self.config["token"])
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "ab") as out, subprocess.Popen(
                command, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                start_new_session=True) as process:
            deadline = time.monotonic() + ACME_TIMEOUT
            try:
                while True:
                    if self.stopped.is_set():
                        raise InterruptedError("service stopping")
                    if time.monotonic() > deadline:
                        raise TimeoutError("acme.sh took too long")
                    try:
                        return process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()


def message(state, name):
    """The settings page's line about the name and its certificate."""
    if not name:
        return ""
    status = read_status(state)
    if status.get("name") != name:
        status = {}
    until = end_date(state) if certificate_for(state, name) else None
    if until:
        text = f"正式证书有效期至 {until}。"
        if not serving(state):
            text += "新证书在下次开机时启用。"
    else:
        text = {"issuing": "正在申请正式证书，通常几分钟；完成后下次开机启用。",
                "retry": "正式证书暂未申请到：请确认盒子能上网、子域名和 token 正确；盒子每小时重试。",
                }.get(status.get("phase"), "等待申请正式证书：盒子联网后自动开始。")
    if status.get("record") == "blocked":
        text += status.get("warning", "已保留原域名记录。")
    if status.get("record") == "failed":
        text += f"更新 {name} 的解析失败，盒子会继续重试。"
    return text


def not_after(state):
    """The installed certificate's end as a Unix time, or None."""
    out = _openssl("x509", "-noout", "-enddate", "-in", str(Path(state) / "tls" / "own" / "fullchain.pem"))
    if out.returncode:
        return None
    try:
        import calendar
        return calendar.timegm(time.strptime(out.stdout.strip().split("=", 1)[1], "%b %d %H:%M:%S %Y %Z"))
    except (IndexError, ValueError):
        return None


def certificate_state(state, name, now=None, soon_days=30):
    """The `certificate` domain of the status (docs/STATUS-MODEL.md): self_signed (no own name), ok,
    expiring_soon (< soon_days), expired, renewing, issuing, failed; with not_after (ISO date) when known.
    Judged by the box clock, which clock_floor keeps from running backwards."""
    if not name:
        return {"state": "self_signed", "reason": None, "not_after": None}
    status = read_status(state)
    if status.get("name") != name:
        status = {}
    phase = status.get("phase")
    end = not_after(state)
    end_text = time.strftime("%Y-%m-%d", time.gmtime(end)) if end else None
    current = now if now is not None else time.time()
    if end is None:
        if phase == "retry":
            return {"state": "failed", "reason": status.get("reason") or "not-obtained", "not_after": None}
        return {"state": "issuing", "reason": None if phase == "issuing" else "waiting-for-internet", "not_after": None}
    if end <= current:
        return {"state": "expired", "reason": status.get("reason") if phase == "retry" else None, "not_after": end_text}
    if phase == "renewing":
        return {"state": "renewing", "reason": None, "not_after": end_text}
    if end - current < soon_days * 86400:
        return {"state": "expiring_soon", "reason": status.get("reason") if phase == "retry" else None, "not_after": end_text}
    return {"state": "ok", "reason": None, "not_after": end_text}


def serving(state):
    """The web server's keystore holds the installed certificate of one's own (boxnet's marker: its hash)."""
    try:
        marker = json.loads((Path(state) / "tls" / "leaf.san.json").read_text())
        chain = (Path(state) / "tls" / "own" / "fullchain.pem").read_bytes()
        return marker.get("own") == hashlib.sha256(chain).hexdigest()[:16]
    except (OSError, ValueError, TypeError, AttributeError):
        return False
