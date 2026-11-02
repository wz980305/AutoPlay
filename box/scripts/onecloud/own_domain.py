"""Optional: an own name with a Let's Encrypt certificate. The only route verified on a Tesla (F50 2026-10-14,
again 2026-11-02): its browser opens https://<name>:18443/ without a certificate warning (tesla_only_box_delta.md 0).
Off unless the owner enters a name in LuCI. Two DNS providers (uci dns_provider):

- duckdns (default): a DuckDNS sub-domain and its token (uci duckdns_domain / duckdns_token). The public DuckDNS
  record is pointed at the router's LAN address (100.96.0.1; DuckDNS takes a private address) by update_record().
- dnspod: a full domain the owner manages in Tencent Cloud DNS (uci own_domain / dnspod_id / dnspod_token). acme.sh's
  dns_dp hook creates the DNS-01 TXT record through the DNSPod API; the A record is the owner's to create in the
  DNSPod console (recommended: <name> -> 100.96.0.1, so the name also resolves when the car asks a public resolver).
  The DNSPod API token can change every record of the account: keep it to a box the owner controls.

In both cases the box's own dnsmasq answers the name locally for the Tesla (tesla_openwrt.OfflineChecks).
- The certificate comes from Let's Encrypt through acme.sh (bundled in acme/) with a DNS-01 challenge: only
  outgoing HTTPS, nothing has to reach the box, so it works over the SIM. It is installed in state/tls/own/,
  which boxnet wraps into the receiver's keystore; a new one loads on the next receiver start, never mid-drive.
  Renewed when less than RENEW_DAYS remain, whenever the box is online.
- The credentials reach acme.sh by its environment only (not its command line); they are never logged or shown.
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
import socket
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from state import tesla_reaches, save_json

SUFFIX = ".duckdns.org"
DOMAIN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
TOKEN = re.compile(r"[A-Za-z0-9-]{16,64}")   # DuckDNS shows a UUID
FQDN = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")
DNSPOD_ID = re.compile(r"\d{3,16}")              # DNSPod API ID (a number)
DNSPOD_TOKEN = re.compile(r"[A-Za-z0-9]{16,64}")  # DNSPod API Token
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
# acme.sh 3.1.6 sends its requests without any timeout: one dead connection held a whole run until ACME_TIMEOUT. A
# curl shim in state/acme/bin bounds every request (D2, DashPlay 2026.10.31); the pinned acme.sh itself is untouched.
ACME_CONNECT_TIMEOUT = 10
ACME_REQUEST_TIMEOUT = 90
ACME_RETRY = 2
# Not a failure: no default route or no DNS yet (boot, SIM registering). Looked at again this often instead of
# spending the 60/120/300/900 s back-off on "no internet" (D1, DashPlay 2026.10.26).
READY_RETRY = 15
DNS_SLEEP = 60             # wait for the TXT record instead of acme.sh's DoH check (blocked on some networks)
ACME_SERVER = os.environ.get("AUTOPLAY_ACME_SERVER", "letsencrypt")   # tests: letsencrypt_test
ACME_HOSTS = {"letsencrypt": "acme-v02.api.letsencrypt.org", "letsencrypt_test": "acme-staging-v02.api.letsencrypt.org"}
PROVIDER_HOSTS = {"duckdns": "www.duckdns.org", "dnspod": "dnsapi.cn"}   # what acme.sh's hook talks to


def sub_domain(text):
    """'MyCar', 'mycar.duckdns.org' -> 'mycar'; ValueError when not a DuckDNS sub-domain."""
    domain = (text or "").strip().lower().removesuffix(SUFFIX)
    if not DOMAIN.fullmatch(domain):
        raise ValueError("DuckDNS 子域名只能包含小写字母、数字和连字符。")
    return domain


def fqdn(text):
    """'Car.Example.com' -> 'car.example.com'; ValueError when not a full domain name."""
    domain = (text or "").strip().lower().rstrip(".")
    if not FQDN.fullmatch(domain):
        raise ValueError("域名格式不对：形如 car.example.com，只能包含字母、数字、连字符和点。")
    return domain


def check_token(token):
    token = (token or "").strip()
    if not TOKEN.fullmatch(token):
        raise ValueError("DuckDNS token 格式不对：在 duckdns.org 登录后页面上方的 token 一栏复制。")
    return token


def check_dnspod_id(text):
    value = (text or "").strip()
    if not DNSPOD_ID.fullmatch(value):
        raise ValueError("DNSPod ID 格式不对：在 DNSPod 控制台「API Token」里复制 ID。")
    return value


def check_dnspod_token(text):
    value = (text or "").strip()
    if not DNSPOD_TOKEN.fullmatch(value):
        raise ValueError("DNSPod Token 格式不对：在 DNSPod 控制台「API Token」里复制 Token。")
    return value


def name_of(config):
    if not config:
        return None
    return config["domain"] if config.get("provider") == "dnspod" else config["domain"] + SUFFIX


def forget_certificate(state):
    """When the name changes or the feature is turned off: the certificate is for the old name."""
    shutil.rmtree(Path(state) / "tls" / "own", ignore_errors=True)
    (Path(state) / "own-domain.json").unlink(missing_ok=True)


def update_record(config, address, timeout=15):
    """Point the name at address (private addresses allowed). The DNSPod A record is managed in its console and
    the box answers the name locally for the Tesla (OfflineChecks), so there is nothing to update here."""
    if config.get("provider") == "dnspod":
        return True
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


def directory_host():
    """The ACME server's host name (acme.sh takes a short name or a full directory URL)."""
    if "://" in ACME_SERVER:
        return urllib.parse.urlsplit(ACME_SERVER).hostname or ""
    return ACME_HOSTS.get(ACME_SERVER, ACME_HOSTS["letsencrypt"])


def has_default_route(proc=Path("/proc")):
    """An IPv4 or IPv6 default route that is up and not a reject route. /proc, since OpenWrt's BusyBox `ip` has no
    JSON (DashPlay default_route_families, the /proc branches)."""
    try:   # Iface Destination Gateway Flags ... Mask ...: /0, up (0x1), not a reject route (0x200)
        for line in (proc / "net/route").read_text().splitlines()[1:]:
            fields = line.split()
            if (len(fields) >= 11 and fields[0] != "lo" and fields[1] == fields[7] == "00000000"
                    and int(fields[3], 16) & 1 and not int(fields[3], 16) & 0x200):
                return True
    except (OSError, ValueError):
        pass
    try:   # ::/0 must be UP and not REJECT; Linux also lists an unreachable ::/0 on lo
        for line in (proc / "net/ipv6_route").read_text().splitlines():
            fields = line.split()
            if (len(fields) == 10 and fields[0] == "0" * 32 and fields[1] == "00" and fields[9] != "lo"
                    and int(fields[8], 16) & 1 and not int(fields[8], 16) & 0x200):
                return True
    except (OSError, ValueError):
        pass
    return False


def network_ready(provider="duckdns", resolve=socket.getaddrinfo, proc=Path("/proc")):
    """None when the box can reach its DNS provider and the CA, else "route" or "dns" (D1). Looked at before
    acme.sh runs: at boot the first attempt landed before the SIM was up and cost the first back-off step."""
    if not has_default_route(proc):
        return "route"
    for host in (PROVIDER_HOSTS.get(provider, PROVIDER_HOSTS["duckdns"]), directory_host()):
        try:
            resolve(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            return "dns"
    return None


CURL_FAILURE = re.compile(r"error code: (\d{1,3})")


def curl_failure(log):
    """The curl exit code from acme.sh's log ("6" name lookup, "28" timeout), digits only."""
    try:
        found = CURL_FAILURE.findall(Path(log).read_text(errors="replace"))
    except OSError:
        return None
    return found[-1] if found else None


def failure_reason(error, log=None):
    """A short code for the status (D3): never a message, which may carry the token. The log is read only when
    this run wrote to it (the caller compares mtimes), so an old failure is not reported again."""
    code = curl_failure(log) if log else None
    if code:
        return "curl" + code
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):   # acme.sh's cap, or openssl hanging
        return "timeout"
    if isinstance(error, ValueError):
        return "certificate"
    if isinstance(error, OSError):
        return "network"
    return "acme"


def reason_text(reason):
    """The settings page's words for failure_reason() and the readiness codes."""
    if reason == "route":
        return "盒子还没有默认路由（SIM 卡还没连上网络）"
    if reason == "dns":
        return "域名解析失败（DNS 服务商或 Let's Encrypt 解析不到）"
    if reason == "timeout":
        return "acme.sh 超时"
    if reason and reason.startswith("curl") and reason[4:].isdigit():
        return f"连接失败（curl 错误 {reason[4:]}）"
    if reason == "network":
        return "网络中断"
    if reason == "certificate":
        return "证书内容不对"
    return "acme.sh 申请没有成功"


def curl_shim(home):
    """A curl in front of acme.sh's own (D2): --connect-timeout/--max-time/--retry on every request. PATH only for the
    acme.sh process; the bundled acme.sh stays byte-identical to its pinned hash. None when curl is not there."""
    real = shutil.which("curl")
    if not real:
        return None
    directory = Path(home) / "bin"
    path = directory / "curl"
    text = ("#!/bin/sh\n"
            f'exec "{real}" --connect-timeout {ACME_CONNECT_TIMEOUT} --max-time {ACME_REQUEST_TIMEOUT} '
            f'--retry {ACME_RETRY} --retry-delay 2 "$@"\n')
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.exists() or path.read_text() != text:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o700)
            with os.fdopen(fd, "w") as out:
                out.write(text)
            path.chmod(0o700)
    except OSError:
        return None
    return str(directory)


def write_status(state, **fields):
    """Fixed, public fields only (phase, record, address): never an error text, which may carry the token."""
    path = Path(state) / "own-domain.json"
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        old = {}
    value = dict(old if isinstance(old, dict) else {}, **fields)
    try:
        save_json(path, value, sync=False)
    except OSError:
        # A full/read-only card must not silently kill the certificate maintenance thread. Its
        # network checks and retry timer can still recover; status publication is best effort.
        pass


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
            say("own name record kept: Tesla cannot reach the current address")
        self.stopped, self.say = stopped, say
        self.sent, self.sent_at = None, 0.0   # address last accepted by DuckDNS, and when
        self.ready = network_ready               # the readiness probe (D1); tests replace it

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
                    self.say(f"{self.config.get('provider', 'duckdns')} {self.name} -> {self.address}: {'OK' if ok else 'failed'}")
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
        log = self.state / "acme" / "acme.log"
        before = None
        try:
            # OpenSSL can time out or fail to start too, not just acme.sh. These failures must use
            # the same retry policy instead of ending the only renewal thread for this boot.
            if certificate_for(self.state, self.name, RENEW_DAYS):
                self.cert_failures = 0
                write_status(self.state, name=self.name, phase="ready")
                return CERT_CHECK
            # D1: no route or no DNS yet is not a failure (boot, SIM registering): look again in READY_RETRY s
            # instead of spending a back-off step; the settings page shows why.
            try:
                missing = self.ready(self.config.get("provider", "duckdns"))
            except Exception:   # never kill the worker on a readiness probe
                missing = "route"
            if missing:
                write_status(self.state, name=self.name, phase="waiting", reason=missing)
                return READY_RETRY
            renewing = certificate_for(self.state, self.name)
            write_status(self.state, name=self.name, phase="renewing" if renewing else "issuing")
            before = log.stat().st_mtime_ns if log.exists() else None
            self.obtain()
            until = end_date(self.state)
        except InterruptedError:
            return CERT_CHECK
        except Exception as error:   # no internet, the DNS provider or Let's Encrypt refused; texts may carry the token
            self.cert_failures += 1
            delay = self.retry_delay()
            after = log.stat().st_mtime_ns if log.exists() else None
            reason = failure_reason(error, log if before is not None and after != before else None)
            write_status(self.state, name=self.name, phase="retry", failures=self.cert_failures, reason=reason)
            self.say(f"certificate for {self.name} deferred ({reason}); next try in {delay} s")
            return delay
        self.cert_failures = 0
        write_status(self.state, name=self.name, phase="ready")
        self.say(f"certificate for {self.name} installed until {until}; used from the next start")
        return CERT_CHECK

    def obtain(self):
        home = self.state / "acme"
        home.mkdir(mode=0o700, exist_ok=True)
        log = home / "acme.log"
        log.unlink(missing_ok=True)   # one run's log only (private, 0600)
        # One worker at a time, also across a supervisor restart while acme.sh is still running.
        fd = os.open(home / "autoplay.lock", os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.config.get("provider") == "dnspod":
                dns, extra_env = ["--dns", "dns_dp"], {"DP_Id": self.config["id"], "DP_Key": self.config["token"]}
            else:
                dns, extra_env = ["--dns", "dns_duckdns"], {"DuckDNS_Token": self.config["token"]}
            # 2: acme.sh still has a certificate it considers current; install that one.
            if self.acme(["--issue", *dns, "--dnssleep", str(DNS_SLEEP), "-d", self.name,
                          "--keylength", "ec-256"], log, extra_env) not in (0, 2):
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

    def acme(self, arguments, log, extra_env=None):
        """acme.sh in its own process group, cancelled when the service stops; the credentials only in its environment."""
        home = self.state / "acme"
        command = [str(self.root / "acme" / "acme.sh"), "--home", str(self.root / "acme"), "--config-home", str(home),
                   "--cert-home", str(home / "certs"), *arguments, "--server", ACME_SERVER, "--no-color"]
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)
        shim = curl_shim(home)   # D2: every request bounded; acme.sh itself unchanged
        if shim:
            env["PATH"] = shim + os.pathsep + env.get("PATH", "")
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
        phase, reason = status.get("phase"), status.get("reason")
        text = {"issuing": "正在申请正式证书，通常几分钟；完成后下次开机启用。",
                "renewing": "正在续签正式证书；完成后下次开机启用。",
                "waiting": f"等待申请正式证书：{reason_text(reason)}，盒子每 15 秒再看一次。",
                "retry": f"正式证书暂未申请到：{reason_text(reason)}。请确认盒子能上网、域名和 DNS 服务商的凭证正确；"
                         "盒子每小时重试。",
                }.get(phase, "等待申请正式证书：盒子联网后自动开始。")
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
        if phase == "waiting":   # D1: no route / no DNS yet, not a failure
            return {"state": "issuing", "reason": status.get("reason") or "waiting-for-internet", "not_after": None}
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
