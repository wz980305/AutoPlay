#!/usr/bin/env python3
"""Run AutoPlay on OpenWrt as one procd service (/etc/init.d/autoplay, package openwrt/autoplay).

Tesla mode only, on the ZTE F50 (tesla_only_box_delta.md): the router owns the network, its LAN is
100.96.0.1/24 (set at install time, uci-defaults in the package), the first access point (5 GHz first) is
handed to the iPhone over Bluetooth, the box answers the Tesla's connectivity checks for as long as it runs
(tesla_openwrt.OfflineChecks), music, calls and Siri go over the car's own Bluetooth, and the receiver runs on
the LAN address with the settings page (iPhones only) on SETTINGS_PORT. Wireless CarPlay only: the F50 has no
USB host (D13).

Supervision (reliability_audit #1, #2, #4, #5): every child is restarted on its own with exponential back-off,
the receiver (JVM) keeps running while Bluetooth is brought up again, Bluetooth is retried in the background
for as long as the service runs (10, 20, 40, then every 60 s) and the receiver is relaunched with wireless once
it is there, the JVM is probed over HTTP every 10 s (three misses restart it), every periodic check is guarded,
and "Wi-Fi missing" counts only after three consecutive misses. The whole service restarts itself only when the
Wi-Fi handed to the iPhone changes or the identity files appear. What the box is doing is published as
RUN/status.json (status_model.py, docs/STATUS-MODEL.md).
Optional: an own name with a Let's Encrypt certificate (own_domain.py; uci dns_provider: a DuckDNS sub-domain, or a
Tencent Cloud DNSPod domain), the one route a Tesla's browser is known to open without a warning; it then replaces
the local name.
"""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import secrets
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.request

from boxnet import ensure_keystore
import clock_floor
from settings_page import SettingsPage
import state as state_files
from status_model import Status
import supervision
import diagnostics
import own_domain
import update
from tesla_openwrt import OfflineChecks
from platform_openwrt import OpenWrtPlatform, RUN, thermal as read_thermal
import viewer_port

# uci autoplay.main: the seven owner-editable keys (tesla_only_box_delta.md section 5). Everything else is a
# constant below; keys of older releases are ignored and cleaned up (obsolete_options).
DEFAULTS = {"enabled": "1",
            # The CarPlay page's HTTPS port. Empty is 18443, or the port an older install saved in
            # state/receiver/config.json (adopted once); it must differ from SETTINGS_PORT, 80, 443 and 7000.
            "viewer_port": "",
            # Seconds without a viewer page before wireless CarPlay is ended, so an iPhone near a box left on
            # does not keep sending its screen (0: never; then a reopened page shows the picture at once).
            "idle_release": "300",
            # A DuckDNS sub-domain and its token: the name becomes <sub-domain>.duckdns.org, with a Let's Encrypt
            # certificate the router obtains and renews itself (own_domain.py). Empty: off.
            "duckdns_domain": "", "duckdns_token": "",
            # A Tencent Cloud (DNSPod) name instead: dns_provider=dnspod with a full domain and the DNSPod API
            # ID/token; the certificate is issued with a DNS-01 challenge through acme.sh's dns_dp hook.
            "dns_provider": "", "own_domain": "", "dnspod_id": "", "dnspod_token": "",
            # Look for a new release once a day (update.py; installed only when someone clicks it), and the URL
            # prefixes tried after GitHub (read by update.py itself).
            "update_check": "1", "update_mirror": ""}
# Every sound is on the Tesla's Bluetooth since 1.3.0 (docs/AUDIO.md, ADR-16): audio_route_navigation (1.1.0-1.2.0)
# joined the keys a box upgraded from an older release may still carry; it is ignored and removed on upgrade.
OBSOLETE_OPTIONS = ("wifi", "settings_port", "java", "name", "bluetooth_service", "dbus_address", "public_ipv6",
                    "shared_lan", "car_music", "car_voice", "tesla_mode", "answer_tesla_checks", "audio_route_navigation",
                    "external_ssid", "external_key", "external_security", "external_channel", "external_network")

# Constants of the Tesla-only box (no uci key): D1, D4, D8, D11, D14.
SETTINGS_PORT = 18080                                   # plain-HTTP settings page; LuCI keeps 80
JAVA = "/usr/lib/autoplay-jre/bin/java"                 # the autoplay-jre package
LOCAL_NAME = state_files.LOCAL_NAME                     # the name without a DuckDNS one
SHARED_LAN = state_files.SHARED_LAN                     # 100.96.0.1/24, set by the package at install time
BLUETOOTH_BUS = f"unix:path={RUN}/bluetooth/system_bus_socket"   # board_zte_f50.py's private D-Bus
RECHECK_EVERY = 10      # seconds between looks at the Wi-Fi handed to the iPhone and the other slow checks
TICK = 2                # seconds between child polls
STATUS_FILE = RUN / "status.json"
WAN_UP_FILE = RUN / "wan-up"       # touched by the hotplug scripts (openwrt/autoplay/files/hotplug-*)
HCI = Path("/sys/class/bluetooth/hci0")


def read_config(uci_text):
    """`uci -q show autoplay` -> the seven options of the main section, with defaults; other keys ignored."""
    config = dict(DEFAULTS)
    for line in (uci_text or "").splitlines():
        match = re.match(r"^autoplay\.main\.(\w+)='?(.*?)'?$", line)
        if match and match.group(1) in DEFAULTS:
            config[match.group(1)] = match.group(2)
    return config


def obsolete_options(uci_text):
    """The uci commands that drop the keys of older releases from autoplay.main (one-shot, idempotent)."""
    found = []
    for line in (uci_text or "").splitlines():
        match = re.match(r"^autoplay\.main\.(\w+)=", line)
        if match and match.group(1) in OBSOLETE_OPTIONS:
            found.append(["delete", f"autoplay.main.{match.group(1)}"])
    return found + [["commit", "autoplay"]] if found else []


def legacy_dns_cleanup(uci_dhcp):
    """`uci -q show dhcp` -> the uci commands that remove what older releases put there for the own name: the
    dhcp.dashplay / dhcp.dashplay6 domain records, local-only server entries and the rebind_domain whitelist
    (tesla_only_box_delta.md D2; the 10.23 prerm forgot rebind_domain). The name is now answered by
    OfflineChecks' address= record alone. [] when nothing is left."""
    kinds, options = {}, {}
    for line in (uci_dhcp or "").splitlines():
        match = re.match(r"^dhcp\.([^.=]+)=(\w+)$", line)
        if match:
            kinds[match.group(1)] = match.group(2)
        match = re.match(r"^dhcp\.([^.=]+)\.(\w+)=(.*)$", line)
        if match:
            options.setdefault(match.group(1), {})[match.group(2)] = re.findall(r"'([^']*)'", match.group(3)) or [match.group(3)]
    names = {name for section in ("dashplay", "dashplay6") for name in options.get(section, {}).get("name", [])}
    changes = [["delete", f"dhcp.{section}"] for section in ("dashplay", "dashplay6") if section in kinds]
    dns = next((section for section, kind in kinds.items() if kind == "dnsmasq"), None)
    if dns:
        for entry in options.get(dns, {}).get("server", []):
            if entry.startswith("/") and entry.endswith("/") and (entry[1:-1] in names or entry[1:-1].endswith(".duckdns.org")):
                changes.append(["del_list", f"dhcp.{dns}.server={entry}"])
        for entry in options.get(dns, {}).get("rebind_domain", []):
            if entry.startswith("/") and entry.endswith("/") and (entry[1:-1] in names or entry[1:-1].endswith(".duckdns.org")):
                changes.append(["del_list", f"dhcp.{dns}.rebind_domain={entry}"])
    return changes + [["commit", "dhcp"]] if changes else []


def lan_warning(address):
    """Why the LAN address is wrong for a Tesla (D1: the package sets 100.96.0.1/24; nothing moves it at run
    time, this only warns): "" when it is in the shared space 100.64.0.0/10."""
    if address is None:
        return ""
    if address.ip in state_files.SHARED_SPACE:
        return ""
    return (f"局域网地址是 {address}，不在 100.64.0.0/10 里，特斯拉的浏览器打不开它。请在 OpenWrt 后台「网络 → 接口 → LAN」"
            f"改回 {SHARED_LAN}，或重新安装 AutoPlay。")


def channel_warning(channel):
    """A Tesla sees 5 GHz channels 36-48 and 149-165 only (tesla_only_box_delta.md 6.1, platform_audit #9)."""
    if channel is None or channel <= 14:
        return "AutoPlay 热点在 2.4 GHz：能用，但 5 GHz（国内信道 149）更稳。" if channel else ""
    if 36 <= channel <= 48 or 149 <= channel <= 165:
        return ""
    return f"特斯拉看不到 AutoPlay 热点的信道 {channel}，请改为 149（国家 CN）或 36。"


def trusted_networks(network):
    """Who may use the settings page: the network of the Wi-Fi handed to the iPhone, where the head unit is,
    not every interface of the router (the WAN or a guest network too; audit 2026-10-13, A5)."""
    return [network["address"].network]


def waiting_trust(planned, lan):
    """Who may open the settings page while the Wi-Fi is not up: the network the configured Wi-Fi will use, or the
    LAN when the configuration names none (its access point switched off, 2026-10-19). [] when neither has an address."""
    if planned:
        return trusted_networks(planned)
    return [lan.network] if lan else []


WAITING_REASONS = [   # platform_openwrt's reasons, for the settings page; others are shown as they are
    (r"no Wi-Fi network is switched on.*", "路由器的 Wi-Fi 都关着"),
    (r"Wi-Fi (.+) is not up yet", r"「\1」还没开启"),
    (r"no Wi-Fi network with a password type.*", "没有 iPhone 能用的加密方式（不加密、WPA2 或 WPA3 个人）"),
    (r"network (\S+) for Wi-Fi (.+) has no IPv4 address yet", r"「\2」所在的网络 \1 还没有地址"),
    (r"Wi-Fi (.+) has no channel yet", r"「\1」还没有信道"),
]


def waiting_warning(why):
    """The settings page's notice while it waits for the Wi-Fi handed to the iPhone."""
    for pattern, text in WAITING_REASONS:
        if re.fullmatch(pattern, why):
            why = re.sub(pattern, text, why)
            break
    return f"AutoPlay 热点还没准备好：{why}。"


TAILSCALE_DROP = re.compile(r'iifname != "tailscale0\*?" ip saddr 100\.64\.0\.0/10 .*\bdrop\b')


def shared_lan_conflict(ip_addresses, lan_device, ruleset=None):
    """`ip -4 -o addr show` (and `nft list ruleset`, None when unreadable) -> why SHARED_LAN cannot work:
    Tailscale's own firewall (it drops 100.64.0.0/10 arriving on any other interface; with
    `tailscale set --netfilter-mode=off` it adds none, and the F50's fw4 zone for tailscale0 lets it in),
    or another interface already in that /24 (a USB MiFi, the SIM's WAN). "" when free. The LAN is not moved
    either way (D1): this is the owner's warning (R6)."""
    tailscale = TAILSCALE_DROP.search(ruleset) if ruleset is not None else None
    for line in (ip_addresses or "").splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[2] != "inet":
            continue
        device = fields[1]
        if device.startswith("tailscale") and (ruleset is None or tailscale):
            return ("Tailscale 的防火墙会丢掉别的网口进来的 100.64.0.0/10 地址：先在路由器上运行 "
                    "tailscale set --netfilter-mode=off（OpenWrt 防火墙要有放行 tailscale0 的区域）")
        try:
            theirs = ipaddress.IPv4Interface(fields[3]).network
        except ValueError:
            continue
        if device != lan_device and theirs.overlaps(SHARED_LAN.network):
            return f"{device} 已在用 {theirs}，与 {SHARED_LAN.network} 冲突"
    return ""


def refresh_network_warning(lan_device, status, base_warning="", path=None):
    """Read live routes without changing them; publish only a warning for settings and LuCI. Written only when
    the text changes (the file is on tmpfs, but LuCI polls it; reliability_audit #11)."""
    try:
        addresses = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=5)
        if addresses.returncode:
            raise OSError("ip failed")
        try:
            nft = subprocess.run(["nft", "list", "ruleset"], capture_output=True, text=True, timeout=10)
            ruleset = nft.stdout if nft.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            ruleset = None
        warning = shared_lan_conflict(addresses.stdout, lan_device, ruleset)
        if warning:
            warning += "。请检查运营商/上游网络。"
    except (OSError, subprocess.SubprocessError):
        warning = "暂时无法检查特斯拉网段冲突，请检查系统网络状态。"
    status["warning"] = "；".join(x for x in (base_warning, warning) if x)
    path = path or RUN / "network-status.json"
    current = state_files.load_json(path, {})
    if not isinstance(current, dict) or current.get("warning") != status["warning"] \
            or time.time() - current.get("checked_at", 0) > 40:   # LuCI shows "unavailable" after 45 s
        state_files.save_json(path, {"warning": status["warning"], "checked_at": int(time.time())}, sync=False)


def own_config(config):
    """The own name and its DNS provider from uci, or None when off or invalid (then said once, never fatal)."""
    if config.get("dns_provider") == "dnspod":
        if not config.get("own_domain"):
            return None
        try:
            return {"domain": own_domain.fqdn(config["own_domain"]), "provider": "dnspod",
                    "id": own_domain.check_dnspod_id(config.get("dnspod_id", "")),
                    "token": own_domain.check_dnspod_token(config.get("dnspod_token", ""))}
        except ValueError:
            print("autoplay.main.own_domain/dnspod_id/dnspod_token invalid: own name off", flush=True)
            return None
    if not config.get("duckdns_domain"):
        return None
    try:
        return {"domain": own_domain.sub_domain(config["duckdns_domain"]), "provider": "duckdns",
                "token": own_domain.check_token(config["duckdns_token"])}
    except ValueError:
        print("autoplay.main.duckdns_domain/duckdns_token invalid: own name off", flush=True)
        return None


def box_name(ddns):
    """The name the head unit opens: the DuckDNS name, else the local one (D11)."""
    return own_domain.name_of(ddns) if ddns else LOCAL_NAME


def plan_of(network):
    """What the receiver depends on: a change in any of these restarts it."""
    return (network["ssid"], network["key"], network["security"], network["channel"], str(network["address"].ip))


def receiver_command(root, network, handoff_file, viewer, idle_release, wireless=True, wait=False):
    """run-receiver.py's command line. Tesla mode is constant (D8): --tesla makes the receiver offer the iPhone no
    audio at all (every sound on the Tesla's Bluetooth, docs/AUDIO.md) and no microphone."""
    return [sys.executable, str(root / "run-receiver.py"), "--root", str(root), "--bind", str(network["address"].ip),
            "--channel", str(network["channel"]), "--security", network["security"],
            "--hotspot", str(handoff_file), "--interface", network["device"], "--web-host", "0.0.0.0",
            "--java", JAVA, "--settings-port", str(SETTINGS_PORT), "--viewer-port", str(viewer),
            "--idle-release", str(idle_release), "--tesla"] \
        + ([] if wireless else ["--no-wireless"]) + (["--bind-wait", "120"] if wait else [])


# Reason codes -------------------------------------------------------------------------------------------

HELPER_REASONS = [   # the board helper's last log line -> a reason word for the status (board_zte_f50.py)
    (r"Marlin3 Bluetooth init failed", "controller-init-failed"),
    (r"did not come up", "controller-timeout"),
    (r"missing .*run .* --setup", "bluez-missing"),
    (r"expected exactly one built-in Bluetooth rfkill", "rfkill"),
    (r"Bluetooth rfkill not found after hci0|rfkill unblock failed", "rfkill"),
    (r"Bluetooth is hard-blocked", "rfkill-hard"),
    (r"HCI controller already exists", "hci-busy"),
    (r"/var/lib/bluetooth belongs to something else", "storage-conflict"),
    (r"(dbus|btattach|bluetoothd) exited with", "daemon-exit"),
]


def helper_reason(log_text, code=None):
    """The reason word for a Bluetooth helper that exited, from the tail of its log."""
    for line in reversed((log_text or "").splitlines()[-20:]):
        for pattern, word in HELPER_REASONS:
            if re.search(pattern, line):
                return word
    return f"helper-exit-{code}" if code is not None else "helper-exit"


BRIDGE_REASON = re.compile(r"bt-bridge: reason=([a-z-]+)")


def bridge_reasons(log_text):
    """The `bt-bridge: reason=<word>` lines of the receiver log, oldest first (linux/bt-bridge/bridge.py)."""
    return BRIDGE_REASON.findall(log_text or "")


def pairing_lost(reasons, limit=2):
    """Two consecutive authentication failures mean the iPhone forgot the pairing: the page tells the owner to
    delete and re-add it (dashplay-tesla's rule, re-implemented; borrowability.md 2b.11)."""
    tail = [r for r in reasons[-limit:]]
    return len(tail) == limit and all(r in ("pairing-lost", "auth-failed") for r in tail)


def phone_state(presence, devices_count=None, reasons=()):
    """The `phone` domain from state/receiver/phone-presence.json and the bridge's reason words."""
    presence = presence or {}
    if presence.get("active"):
        return "live", None
    if pairing_lost(list(reasons)):
        return "pairing-lost", reasons[-1]
    declined = presence.get("declined") or {}
    if declined:
        return "declined", None
    if reasons:
        return "idle", reasons[-1]
    return "idle", None


# Managers ------------------------------------------------------------------------------------------------

class BluetoothManager:
    """The F50's Bluetooth: the board helper (dbus-daemon, btattach, bluetoothd) as a child restarted on its own,
    and the adapter powered in the background with 10, 20, 40, then 60 s between tries for as long as the
    service runs (reliability_audit #2). `on_powered` is called (from the main thread, in tick) when the adapter
    comes up after the receiver was started without it."""

    def __init__(self, platform, root, state, status, say, clock=time.monotonic, hci=HCI):
        self.platform, self.root, self.state, self.status, self.say = platform, root, state, status, say
        self.clock, self.hci = clock, hci
        self.restarter = supervision.Restarter("bluetooth", first=5.0, cap=60.0, degraded_after=5, clock=clock)
        self.schedule = supervision.Schedule(clock=clock)
        self.powered = False
        self.attempt = None      # the running power attempt: [thread, result]
        self.generation = 0
        self.on_powered = None
        self.helper_started_at = None

    def command(self):
        return [sys.executable, str(self.root / "board_zte_f50.py"), "--state", str(self.state)]

    def start(self):
        self.generation += 1
        self.platform.start("bluetooth", self.command())
        self.restarter.started()
        self.helper_started_at = self.clock()
        self.schedule.reset()
        self.powered = False
        self.status.set("bluetooth", "starting", "helper-starting")

    def helper(self):
        return self.platform.child("bluetooth")

    def hci_present(self):
        return self.hci.exists()

    def power_once(self):
        """One attempt to power the adapter (bluetoothctl, up to ~40 s): run off the main loop."""
        try:
            return bool(self.platform.power_bluetooth())
        except (subprocess.SubprocessError, OSError):
            return False

    def tick(self):
        child = self.helper()
        if child is not None and child.poll() is not None:
            try:
                log = (self.platform.run / "bluetooth.log").read_text(errors="replace")
            except OSError:
                log = ""
            reason = helper_reason(log, child.returncode)
            delay = self.restarter.failed(reason)
            self.platform.forget_child("bluetooth")
            self.powered = False
            self.say(f"bluetooth helper exited ({reason}); restart in {delay:.0f} s"
                     + (" [degraded]" if self.restarter.degraded else ""))
            self.status.set("bluetooth", "failed", reason, degraded=self.restarter.degraded, retry_in=round(delay))
            return
        if child is None:
            if self.restarter.ready():
                self.say("bluetooth helper starting again")
                self.start()
            return
        if self.powered:
            if not self.hci_present():
                # The combo chip reset (a Wi-Fi firmware recovery) and took the controller with it: the helper's
                # bluetoothd may still run, but the vendor firmware is gone. Start it over (reliability_audit #15).
                self.say("hci0 disappeared: restarting the Bluetooth helper")
                self.platform.stop_child("bluetooth", timeout=15)
                self.restarter.failed("hci-lost")
                self.powered = False
                self.status.set("bluetooth", "failed", "hci-lost", retry_in=round(self.restarter.due - self.clock()))
            else:
                self.restarter.recovered()
            return
        # Not powered yet: try when the schedule says so, off the main loop.
        if self.attempt is not None:
            thread, result, generation = self.attempt
            if thread.is_alive():
                return
            self.attempt = None
            if generation != self.generation:
                return   # the result belongs to a helper that exited; never mark its replacement powered
            if result and result[0]:
                self.powered = True
                self.schedule.reset()
                self.status.set("bluetooth", "on", None)
                self.say(f"boot {self.clock():.2f}s bluetooth powered")
                if self.on_powered:
                    self.on_powered()
                return
            delay = self.schedule.failed()
            long_wait = self.schedule.attempt >= 4   # past 10+20+40 s: say so, keep trying
            self.status.set("bluetooth", "failed" if long_wait else "starting",
                            "adapter-not-powered" if long_wait else "powering", retry_in=round(delay))
            if long_wait:
                self.say(f"Bluetooth adapter still not powered after {self.schedule.attempt} tries; retrying every {delay:.0f} s")
            return
        if self.schedule.due():
            result = []
            thread = threading.Thread(target=lambda: result.append(self.power_once()), name="bluetooth-power", daemon=True)
            thread.start()
            self.attempt = (thread, result, self.generation)


class ReceiverManager:
    """The receiver (run-receiver.py -> JVM): restarted on its own with back-off, probed over HTTP every 10 s
    (three misses restart it), relaunched with wireless once Bluetooth comes up (reliability_audit #1, #5)."""

    def __init__(self, platform, status, say, viewer, command, clock=time.monotonic, probe=None):
        self.platform, self.status, self.say, self.viewer, self.command = platform, status, say, viewer, command
        self.clock = clock
        self.restarter = supervision.Restarter("receiver", first=2.0, cap=60.0, degraded_after=5, clock=clock)
        self.liveness = supervision.Liveness(limit=3, every=10.0, clock=clock)
        self.probe = probe or self.http_probe
        self.probing = None
        self.generation = 0
        self.network = None
        self.wireless = True
        self.wanted = False

    def http_probe(self):
        """GET the receiver's own display endpoint on the loopback (TLS unverified: its certificate is for the
        LAN name). Any HTTP answer, even 401, means the JVM serves."""
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(f"https://127.0.0.1:{self.viewer}/api/display", timeout=3, context=context):
                return True
        except urllib.error.HTTPError:
            return True
        except Exception:   # noqa: BLE001 - connection refused, TLS failure, timeout: not alive
            return False

    def launch(self, network, wireless, wait=False):
        self.generation += 1
        self.network, self.wireless, self.wanted = network, wireless, True
        self.platform.start("receiver", self.command(network, wireless, wait))
        self.restarter.started()
        self.liveness.reset(grace=90.0)   # the JVM needs ~15-40 s before it listens; be generous at boot
        self.status.set("system", "starting", None)

    def relaunch(self, network=None, wireless=None, why="relaunch"):
        self.say(f"receiver relaunch: {why}")
        self.platform.stop_child("receiver", timeout=40)
        self.launch(network or self.network, self.wireless if wireless is None else wireless)

    def tick(self):
        if not self.wanted:
            return
        child = self.platform.child("receiver")
        if child is not None and child.poll() is not None:
            reason = f"receiver-exit-{child.returncode}"
            delay = self.restarter.failed(reason)
            self.platform.forget_child("receiver")
            self.say(f"receiver exited with {child.returncode}; restart in {delay:.0f} s"
                     + (" [degraded]" if self.restarter.degraded else ""))
            self.status.set("system", "degraded" if self.restarter.degraded else "restarting", reason,
                            retry_in=round(delay))
            return
        if child is None:
            if self.restarter.ready():
                self.say("receiver starting again")
                self.launch(self.network, self.wireless)
            return
        if self.probing is not None:
            thread, result, generation = self.probing
            if thread.is_alive():
                return
            self.probing = None
            if generation != self.generation:
                return   # do not cancel the new JVM's startup grace with a result from the old one
            alive = bool(result and result[0])
            if self.liveness.record(alive):
                self.say("receiver answers no HTTP for 30 s: restarting it")
                self.restarter.failed("receiver-liveness")
                self.platform.stop_child("receiver", timeout=10)
                self.status.set("system", "restarting", "receiver-liveness", retry_in=round(self.restarter.due - self.clock()))
                return
            if alive:
                self.restarter.recovered()
                self.status.set("system", "degraded" if self.restarter.degraded else "ok",
                                self.restarter.reason if self.restarter.degraded else None)
            return
        if self.liveness.due():
            result = []
            thread = threading.Thread(target=lambda: result.append(self.probe()), name="receiver-probe", daemon=True)
            thread.start()
            self.probing = (thread, result, self.generation)


# The service ----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    shown = subprocess.run(["uci", "-q", "show", "autoplay"], capture_output=True, text=True, timeout=10).stdout
    config = read_config(shown)
    # Empty in the uci means 18443, or an owner's older state/receiver/config.json value: an update keeps it.
    viewer = (int(config["viewer_port"]) if str(config.get("viewer_port", "")).isdigit()
              else viewer_port.resolve(root / "state"))
    if viewer == SETTINGS_PORT or not viewer_port.valid(viewer):
        raise ValueError("Invalid autoplay.main.viewer_port")
    idle_release = int(config["idle_release"]) if config["idle_release"].isdigit() else 300
    ddns = own_config(config)
    name = box_name(ddns)
    for relative in ["run-receiver.py", "phone-presence.py", "pair-phone.py", "pairing_window.py", "settings_page.py",
                     "settings_ui.py", "platform_openwrt.py", "diagnostics.py", "tesla_openwrt.py", "board_zte_f50.py",
                     "linux-bt-bridge/bt-bridge"]:
        if not (root / relative).is_file():
            raise RuntimeError("Missing runtime input: " + relative)
    if not Path(JAVA).is_file():
        raise RuntimeError(f"Java not found at {JAVA}: install the autoplay-jre package")
    identity = [root / "identity/offline-mfi/identity.pk8", root / "identity/offline-mfi/certificate.p7b"]

    def identity_ok():
        return all(path.is_file() and path.stat().st_size > 0 for path in identity)

    if args.check:
        print("Service configuration and runtime files checked; no services changed")
        return

    os.umask(0o077)
    RUN.mkdir(mode=0o700, parents=True, exist_ok=True)
    # The board helper puts its own bluetoothctl in RUN/bin; every child inherits PATH and the bus.
    os.environ["PATH"] = f"{RUN / 'bin'}:{os.environ.get('PATH', '/usr/sbin:/usr/bin:/sbin:/bin')}"
    os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = BLUETOOTH_BUS
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"   # no .pyc writes on the SD card from the children
    state = root / "state"
    state.mkdir(mode=0o700, exist_ok=True)
    stopped = threading.Event()
    reexec = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        # A stop wins over a restart asked for meanwhile (2026-10-14).
        signal.signal(sig, lambda *_: (reexec.clear(), reexec.append(None), stopped.set()))

    def say(text):
        """procd sends stdout to logread, which the F50's Wi-Fi driver floods within seconds: keep our
        own lines in RUN/supervisor.log too (mirrored to state/logs like every RUN/*.log)."""
        print(text, flush=True)
        try:
            with (RUN / "supervisor.log").open("a") as log:
                log.write(text + "\n")
        except OSError:
            pass

    def mark(step):
        say(f"boot {time.monotonic():.2f}s {step}")   # seconds since kernel start

    # Never trust a clock earlier than the last one seen (no RTC; reliability_audit #10).
    floor_moved = clock_floor.apply(state)
    if floor_moved:
        say(f"clock moved forward to the last known time ({floor_moved})")
    # An update cut by a power loss is finished or rolled back before anything else runs (reliability_audit #8).
    recovered = update.recover(root, say)
    if recovered:
        say(f"update journal: {recovered}")
    # One-shot clean-up of older releases' settings and DNS records (idempotent; the package postinst does the
    # same, this covers a bundle installed by hand).
    for change in obsolete_options(shown):
        subprocess.run(["uci", *change], check=False, capture_output=True, timeout=10)
    # Keep the uci mirroring the effective port, so the LuCI link and field show it (an owner's older
    # state/receiver/config.json value is adopted once; the uci survives package updates).
    if str(viewer) != config.get("viewer_port", ""):
        subprocess.run(["uci", "set", f"autoplay.main.viewer_port={viewer}"], check=False, capture_output=True, timeout=10)
        subprocess.run(["uci", "commit", "autoplay"], check=False, capture_output=True, timeout=10)
        config["viewer_port"] = str(viewer)
    platform = OpenWrtPlatform(run=RUN)
    platform.bluetooth_state = state
    have_identity = identity_ok()
    status = Status(STATUS_FILE, mode="openwrt", entries=[],
                    home=f"http://{name}:{SETTINGS_PORT}/", own_name=name if ddns else None, name=name,
                    viewer_port=viewer)
    status.set("identity", "provided" if have_identity else "missing", None if have_identity else "files-missing")
    status.set("update", "current" if config["update_check"] != "0" else "check-off", None)

    def request_reexec(reason):
        reexec.append(reason)
        stopped.set()

    trusted = []   # the network the settings page serves, once the Wi-Fi is known (it starts after that)
    settings = SettingsPage(state, status.snapshot, request_reexec, lambda: list(trusted), root=root,
                            thermal=read_thermal)
    offline_checks = OfflineChecks(state, platform=platform)
    maintainer = []   # own_domain.Maintainer, when an own name is set
    handoff_file = RUN / "handoff.json"

    def command(network, wireless, wait):
        state_files.save_json(handoff_file, {"ssid": network["ssid"], "passphrase": network["key"]}, sync=False)
        os.environ["CARPLAY_NETWORK_EPOCH"] = secrets.token_hex(4)
        return receiver_command(root, network, handoff_file, viewer, idle_release, wireless, wait)

    bluetooth = BluetoothManager(platform, root, state, status, say)
    receiver = ReceiverManager(platform, status, say, viewer, command)
    guard = {name: supervision.Guard(name, say) for name in ("tesla", "warning", "wifi", "certificate", "system", "phone", "update")}

    def wifi_status(network, reason=None):
        if network:
            status.set("wifi", "up", None, ssid=network["ssid"], channel=network["channel"], address=str(network["address"].ip))
        else:
            status.set("wifi", "waiting", (reason or "")[:120] or None)

    def certificate_status():
        info = own_domain.certificate_state(state, name if ddns else None)
        status.set("certificate", info["state"], info.get("reason"), not_after=info.get("not_after"))

    def update_status():
        found, progress = update.read(state / "update-check.json"), update.read(state / "update-status.json")
        if update.running(root):
            status.set("update", "installing", progress.get("phase"))
        elif progress.get("phase") == "failed" and time.time() - progress.get("at", 0) < 86400:
            status.set("update", "failed", (progress.get("message") or "")[:80])
        elif found.get("error"):
            status.set("update", "check-failed", found["error"][:80])
        elif found.get("available"):
            status.set("update", "available", found.get("latest"))
        elif config["update_check"] == "0":
            status.set("update", "check-off", None)
        else:
            status.set("update", "current", found.get("latest"))

    def system_status():
        data = platform.diagnostics()
        temp = data.get("temp_c")
        if temp is not None:
            extra = {"temp_c": temp}
            if temp >= 95:
                status.set("system", status.state("system"), "hot", **extra)
            else:
                current = status.domain("system")
                status.set("system", current["state"], None if current.get("reason") == "hot" else current.get("reason"), **extra)

    def tesla_status():
        offline_checks.refresh(status)
        if status.get("tesla_error"):
            status.set("tesla", "failed", "plumbing: " + str(status.get("tesla_error"))[:80])
        else:
            status.set("tesla", "on" if status.get("tesla_offline") else "off", None)
        upstream = status.get("tesla_upstream")
        status.set("uplink", {"online": "online", "offline": "offline"}.get(upstream, "unknown"), None)

    def phone_status():
        presence = state_files.load_json(state / "receiver/phone-presence.json", {}) or {}
        try:
            log = (RUN / "receiver.log").read_text(errors="replace")
        except OSError:
            log = ""
        phone, reason = phone_state(presence, reasons=bridge_reasons(log)[-5:])
        status.set("phone", phone, reason, active=presence.get("active"))

    try:
        offline_checks.restore()  # a crashed run's uci dhcp fields go back before they are written again
        mark("supervisor start")
        # Full logs on the SD card (bounded, flushed every minute and on errors), so that a drive can be
        # analysed after the power is cut.
        mirror = diagnostics.LogMirror(state / "logs", RUN, platform.boot_id())
        mirror.start(stopped)

        # Bluetooth at once, beside the Wi-Fi: the F50's controller takes ~10 s to come up, about as long as
        # its Wi-Fi. The board helper is always ours (the F50 is the only target).
        bluetooth.start()

        # The JVM needs several seconds before it first invites the iPhone: start it on what the Wi-Fi
        # configuration says while the radio comes up, and check it against the live Wi-Fi below.
        early = None
        if have_identity:
            early, _ = platform.handoff(live=False)
            if early:
                ensure_keystore(state)
                receiver.launch(early, True, wait=True)
                mark(f"receiver launched early for {early['ssid']}")

        # The Wi-Fi comes up some seconds after procd starts us; wait for it rather than fail. The settings page
        # opens meanwhile, so that a Wi-Fi that never comes up (the router's own switched off) still leaves a page
        # saying why (2026-10-19). Bluetooth and the receiver are ticked meanwhile.
        reason = ""
        network = None
        planned = early or platform.handoff(live=False)[0]
        settings_open = False
        waited_since = time.monotonic()
        while not stopped.is_set():
            network, why = platform.handoff()
            if network:
                break
            if why != reason:
                say(f"waiting: {why}")
                reason = why
                status["warning"] = waiting_warning(why)
                wifi_status(None, why)
            bluetooth.tick()
            receiver.tick()
            if not settings_open and time.monotonic() - waited_since >= 5:   # a Wi-Fi coming up as usual needs a few seconds more
                lan = None if planned else platform.interface_network("lan")
                trusted[:] = waiting_trust(planned, lan)
                # Without any address the page answers the router itself only: an online update still sees the
                # service up (update.py).
                host = str((planned["address"] if planned else lan).ip) if trusted else "127.0.0.1"
                status["home"] = f"http://{host}:{SETTINGS_PORT}/"
                settings.start(SETTINGS_PORT)
                settings_open = True
                say(f"settings page open on {host} while waiting for the Wi-Fi")
            stopped.wait(1)
        if stopped.is_set():
            raise InterruptedError("Service stopping")
        status.pop("warning", None)
        wifi_status(network)
        mark(f"Wi-Fi {network['ssid']} up on channel {network['channel']}")
        address = network["address"]
        platform.interface, platform.ap_interface = network["device"], network["ifname"]
        host = str(address.ip)
        base_warning = "；".join(x for x in (lan_warning(address), channel_warning(network["channel"])) if x)
        if base_warning:
            say(f"warning: {base_warning}")
        renewed = ensure_keystore(state)
        status.update(ssid=network["ssid"], home=f"http://{host}:{SETTINGS_PORT}/",
                      entries=[f"https://{name}:{viewer}/", f"https://{host}:{viewer}/"])
        if ddns:
            maintainer.append(own_domain.Maintainer(root, ddns, host, stopped, say, tesla=True, wake_file=WAN_UP_FILE))
            maintainer[0].start()
        guard["certificate"](certificate_status)
        refresh_network_warning(network["device"], status, base_warning)
        trusted[:] = trusted_networks(network)
        if not settings_open:
            settings.start(SETTINGS_PORT)
        # The Tesla's connectivity checks are answered for as long as the box runs (D4): the LAN never flips
        # with the SIM's signal, only the upstream status text does. A failure is a status reason, never fatal.
        offline_checks.start(network, name, SETTINGS_PORT, status)
        guard["tesla"](tesla_status)
        diagnostics.start(stopped, diagnostics.DiagLog(state / "diag"), RUN / "receiver.log", platform, status,
                          state=state)
        # A new release is looked for once a day and only shown (LuCI, settings page); nothing installs by itself.
        threading.Thread(target=update.checker, args=(root, stopped, config["update_check"] != "0"),
                         name="update-check", daemon=True).start()

        def on_powered():
            # Bluetooth came up after the receiver was started without it: relaunch it with wireless.
            if have_identity and receiver.wanted and not receiver.wireless:
                receiver.relaunch(network, True, why="Bluetooth came up")
        bluetooth.on_powered = on_powered

        if have_identity:
            wireless = bluetooth.powered
            # A renewed certificate needs a new receiver: it reads the keystore once (audit A6).
            if early and plan_of(early) == plan_of(network) and not renewed:
                mark("early receiver kept" + ("" if wireless else " (Bluetooth still coming up)"))
                receiver.network = network
                receiver.wireless = True   # launched early with wireless: the JVM waits for the bridge itself
            else:
                if early:
                    mark("early receiver relaunched: the live Wi-Fi or certificate differs")
                    receiver.relaunch(network, True, why="live Wi-Fi or certificate")
                else:
                    receiver.launch(network, True)
        else:
            say("MFi identity missing: settings page only, CarPlay starts once the files are added")
        say(f"AutoPlay services started on {network['ssid']} ({host}, channel {network['channel']})")
        plan = plan_of(network)
        misses = supervision.Misses(limit=3)
        next_check = time.monotonic() + RECHECK_EVERY
        while not stopped.wait(TICK):
            if not have_identity and identity_ok():
                request_reexec("MFi identity added")
                continue
            # Rate-limited internally. Persist hourly even without WAN/NTP events (or when the
            # certificate thread consumed the shared wake file before this loop saw it).
            clock_floor.touch(state)
            bluetooth.tick()
            receiver.tick()
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + RECHECK_EVERY
                guard["tesla"](tesla_status)
                guard["warning"](refresh_network_warning, network["device"], status, base_warning)
                guard["phone"](phone_status)
                guard["system"](system_status)
                guard["certificate"](certificate_status)
                guard["update"](update_status)
                found = guard["wifi"](platform.handoff)
                if found is None:
                    continue   # the check itself failed: counted by the guard, not as a missing Wi-Fi
                now, why = found
                if now is None:
                    if misses.miss():
                        request_reexec(why)
                    else:
                        say(f"Wi-Fi not seen ({misses.count}/{misses.limit}): {why}")
                else:
                    misses.hit()
                    if plan_of(now) != plan:
                        request_reexec("Wi-Fi changed")
    except InterruptedError:
        pass
    except Exception as error:   # noqa: BLE001 - say why before dying (reliability_audit #14); procd restarts us
        import traceback
        say(f"fatal: {type(error).__name__}: {error}")
        say(traceback.format_exc())
        state_files.save_json(state / "last-exit.json", {"reason": f"{type(error).__name__}: {error}",
                                                        "uptime": round(time.monotonic()), "at": int(time.time())})
        raise
    finally:
        stopped.set()
        for worker in maintainer:
            worker.join(10)   # acme.sh is stopped first: no signer left running into the restarted service
        offline_checks.restore()
        settings.stop()
        platform.stop_all()
        say("AutoPlay services stopped")
    if reexec and reexec[0] is not None:
        say(f"restarting: {reexec[0]}")
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), "--root", str(root)])


if __name__ == "__main__":
    main()
