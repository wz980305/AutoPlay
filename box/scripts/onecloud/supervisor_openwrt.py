#!/usr/bin/env python3
"""Run DashPlay on OpenWrt as one procd service (/etc/init.d/dashplay, package openwrt/dashplay).

Tesla mode only, on the ZTE F50 (tesla_only_box_delta.md): the router owns the network, its LAN is
100.96.0.1/24 (set at install time, uci-defaults in the package), the first access point (5 GHz first) is
handed to the iPhone over Bluetooth, the box answers the Tesla's connectivity checks for as long as it runs
(tesla_openwrt.OfflineChecks), music, calls and Siri go over the car's own Bluetooth, and the receiver runs on
the LAN address with the settings page (iPhones only) on SETTINGS_PORT. The supervisor restarts itself when
that Wi-Fi changes. Wireless CarPlay only: the F50 has no USB host (D13).
Optional: a DuckDNS name with a Let's Encrypt certificate (uci duckdns_domain / duckdns_token, own_domain.py),
the one route a Tesla's browser is known to open without a warning; it then replaces the local name.
"""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time

from boxnet import ensure_keystore
from settings_page import SettingsPage
import state as state_files
import diagnostics
import own_domain
import update
from tesla_openwrt import OfflineChecks
from platform_openwrt import OpenWrtPlatform, RUN
import viewer_port

# uci dashplay.main: the seven owner-editable keys (tesla_only_box_delta.md section 5). Everything else is a
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
            # Look for a new release once a day (update.py; installed only when someone clicks it), and the URL
            # prefixes tried after GitHub (read by update.py itself).
            "update_check": "1", "update_mirror": ""}
OBSOLETE_OPTIONS = ("wifi", "settings_port", "java", "name", "bluetooth_service", "dbus_address", "public_ipv6",
                    "shared_lan", "car_music", "car_voice", "tesla_mode", "answer_tesla_checks",
                    "external_ssid", "external_key", "external_security", "external_channel", "external_network")

# Constants of the Tesla-only box (no uci key): D1, D4, D8, D11, D14.
SETTINGS_PORT = 18080                                   # plain-HTTP settings page; LuCI keeps 80
JAVA = "/usr/lib/dashplay-jre/bin/java"                 # the dashplay-jre package
LOCAL_NAME = state_files.LOCAL_NAME                     # the name without a DuckDNS one
SHARED_LAN = state_files.SHARED_LAN                     # 100.96.0.1/24, set by the package at install time
BLUETOOTH_BUS = f"unix:path={RUN}/bluetooth/system_bus_socket"   # board_zte_f50.py's private D-Bus
RECHECK_EVERY = 10      # seconds between looks at the Wi-Fi handed to the iPhone
# Seconds the F50's controller gets to power on before the receiver is launched without Bluetooth (the
# background retries of the reliability work come next; reliability_audit #2).
BLUETOOTH_WAIT = 60


def read_config(uci_text):
    """`uci -q show dashplay` -> the seven options of the main section, with defaults; other keys ignored."""
    config = dict(DEFAULTS)
    for line in (uci_text or "").splitlines():
        match = re.match(r"^dashplay\.main\.(\w+)='?(.*?)'?$", line)
        if match and match.group(1) in DEFAULTS:
            config[match.group(1)] = match.group(2)
    return config


def obsolete_options(uci_text):
    """The uci commands that drop the keys of older releases from dashplay.main (one-shot, idempotent)."""
    found = []
    for line in (uci_text or "").splitlines():
        match = re.match(r"^dashplay\.main\.(\w+)=", line)
        if match and match.group(1) in OBSOLETE_OPTIONS:
            found.append(["delete", f"dashplay.main.{match.group(1)}"])
    return found + [["commit", "dashplay"]] if found else []


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
            f"改回 {SHARED_LAN}，或重新安装 DashPlay。")


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
    return (f"交给 iPhone 的 Wi-Fi 还没准备好：{why}。请在 OpenWrt 后台「网络 → 无线」或「服务 → DashPlay」检查；"
            "准备好后 DashPlay 会自动继续。")


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
    """The DuckDNS sub-domain and token from uci, or None when off or invalid (then said once, never fatal)."""
    if not config["duckdns_domain"]:
        return None
    try:
        return {"domain": own_domain.sub_domain(config["duckdns_domain"]),
                "token": own_domain.check_token(config["duckdns_token"])}
    except ValueError:
        print("dashplay.main.duckdns_domain/duckdns_token invalid: own name off", flush=True)
        return None


def box_name(ddns):
    """The name the head unit opens: the DuckDNS name, else the local one (D11)."""
    return own_domain.name_of(ddns) if ddns else LOCAL_NAME


def plan_of(network):
    """What the receiver depends on: a change in any of these restarts it."""
    return (network["ssid"], network["key"], network["security"], network["channel"], str(network["address"].ip))


def receiver_command(root, network, handoff_file, viewer, idle_release, wireless=True, wait=False):
    """run-receiver.py's command line. Tesla mode is constant (D8): --tesla makes the receiver offer no
    microphone, no calls and no Siri, and the page play prompts louder."""
    return [sys.executable, str(root / "run-receiver.py"), "--root", str(root), "--bind", str(network["address"].ip),
            "--channel", str(network["channel"]), "--security", network["security"],
            "--hotspot", str(handoff_file), "--interface", network["device"], "--web-host", "0.0.0.0",
            "--java", JAVA, "--settings-port", str(SETTINGS_PORT), "--viewer-port", str(viewer),
            "--idle-release", str(idle_release), "--tesla"] \
        + ([] if wireless else ["--no-wireless"]) + (["--bind-wait", "120"] if wait else [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    shown = subprocess.run(["uci", "-q", "show", "dashplay"], capture_output=True, text=True, timeout=10).stdout
    config = read_config(shown)
    # Empty in the uci means 18443, or an owner's older state/receiver/config.json value: an update keeps it.
    viewer = (int(config["viewer_port"]) if str(config.get("viewer_port", "")).isdigit()
              else viewer_port.resolve(root / "state"))
    if viewer == SETTINGS_PORT or not viewer_port.valid(viewer):
        raise ValueError("Invalid dashplay.main.viewer_port")
    idle_release = int(config["idle_release"]) if config["idle_release"].isdigit() else 300
    ddns = own_config(config)
    name = box_name(ddns)
    for relative in ["run-receiver.py", "phone-presence.py", "pair-phone.py", "pairing_window.py", "settings_page.py",
                     "settings_ui.py", "platform_openwrt.py", "diagnostics.py", "tesla_openwrt.py", "board_zte_f50.py",
                     "linux-bt-bridge/bt-bridge"]:
        if not (root / relative).is_file():
            raise RuntimeError("Missing runtime input: " + relative)
    if not Path(JAVA).is_file():
        raise RuntimeError(f"Java not found at {JAVA}: install the dashplay-jre package")
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
    # One-shot clean-up of older releases' settings and DNS records (idempotent; the package postinst does the
    # same, this covers a bundle installed by hand).
    for change in obsolete_options(shown):
        subprocess.run(["uci", *change], check=False, capture_output=True, timeout=10)
    # Keep the uci mirroring the effective port, so the LuCI link and field show it (an owner's older
    # state/receiver/config.json value is adopted once; the uci survives package updates).
    if str(viewer) != config.get("viewer_port", ""):
        subprocess.run(["uci", "set", f"dashplay.main.viewer_port={viewer}"], check=False, capture_output=True, timeout=10)
        subprocess.run(["uci", "commit", "dashplay"], check=False, capture_output=True, timeout=10)
        config["viewer_port"] = str(viewer)
    platform = OpenWrtPlatform(run=RUN)
    platform.bluetooth_state = state
    stopped = threading.Event()
    reexec = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        # A stop wins over a restart asked for meanwhile (2026-10-14).
        signal.signal(sig, lambda *_: (reexec.clear(), reexec.append(None), stopped.set()))
    have_identity = identity_ok()
    status = {"mode": "openwrt", "entries": [], "identity": have_identity, "home": f"http://{name}:{SETTINGS_PORT}/",
              "own_name": name if ddns else None, "name": name}

    def wait_for(predicate, seconds, interval=0.2):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if stopped.is_set():
                raise InterruptedError("Service stopping")
            if predicate():
                return
            stopped.wait(interval)
        raise TimeoutError("Service dependency did not become ready")

    def request_reexec(reason):
        reexec.append(reason)
        stopped.set()

    trusted = []   # the network the settings page serves, once the Wi-Fi is known (it starts after that)
    settings = SettingsPage(state, lambda: status, request_reexec, lambda: list(trusted))
    offline_checks = OfflineChecks(state, platform=platform)
    maintainer = []   # own_domain.Maintainer, when a DuckDNS name is set

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

    handoff_file = RUN / "handoff.json"

    def launch(network, wireless, wait=False):
        state_files.save_json(handoff_file, {"ssid": network["ssid"], "passphrase": network["key"]}, sync=False)
        os.environ["CARPLAY_NETWORK_EPOCH"] = secrets.token_hex(4)
        platform.start("receiver", receiver_command(root, network, handoff_file, viewer, idle_release, wireless, wait))

    try:
        offline_checks.restore()  # a crashed run's uci dhcp fields go back before they are written again
        mark("supervisor start")
        # Full logs on the SD card, so that a drive can be analysed after the power is cut.
        diagnostics.LogMirror(state / "logs", RUN, platform.boot_id()).start(stopped)

        # Bluetooth at once, beside the Wi-Fi: the F50's controller takes ~10 s to come up, about as long as
        # its Wi-Fi. The board helper is always ours (the F50 is the only target).
        platform.start("bluetooth", [sys.executable, str(root / "board_zte_f50.py"), "--state", str(state)])
        bluetooth = []

        def power_bluetooth():
            try:   # bluetoothd (or the board helper's bluetoothctl) may come up after us
                return platform.power_bluetooth()
            except (subprocess.SubprocessError, FileNotFoundError):
                return False

        def bring_up_bluetooth():
            try:
                wait_for(power_bluetooth, BLUETOOTH_WAIT, interval=0.5)
                mark("bluetooth powered")
                bluetooth.append(True)
            except TimeoutError:
                say("Bluetooth adapter did not power on: no CarPlay until it does")
                bluetooth.append(False)
            except InterruptedError:
                bluetooth.append(False)

        bluetooth_thread = threading.Thread(target=bring_up_bluetooth, name="bluetooth-power", daemon=True)
        bluetooth_thread.start()

        # The JVM needs several seconds before it first invites the iPhone: start it on what the Wi-Fi
        # configuration says while the radio comes up, and check it against the live Wi-Fi below.
        early = None
        if have_identity:
            early, _ = platform.handoff(live=False)
            if early:
                ensure_keystore(state)
                launch(early, True, wait=True)
                mark(f"receiver launched early for {early['ssid']}")

        # The Wi-Fi comes up some seconds after procd starts us; wait for it rather than fail. The settings page
        # opens meanwhile, so that a Wi-Fi that never comes up (the router's own switched off) still leaves a page
        # saying why (2026-10-19).
        reason = ""
        network = None
        planned = early or platform.handoff(live=False)[0]
        settings_open = False
        while not stopped.is_set():
            network, why = platform.handoff()
            if network:
                break
            if why != reason:
                say(f"waiting: {why}")
                reason = why
                status["warning"] = waiting_warning(why)
            if not settings_open and not stopped.wait(5):   # a Wi-Fi coming up as usual needs a few seconds more
                lan = None if planned else platform.interface_network("lan")
                trusted[:] = waiting_trust(planned, lan)
                # Without any address the page answers the router itself only: an online update still sees the
                # service up (update.py).
                host = str((planned["address"] if planned else lan).ip) if trusted else "127.0.0.1"
                status["home"] = f"http://{host}:{SETTINGS_PORT}/"
                settings.start(SETTINGS_PORT)
                settings_open = True
                say(f"settings page open on {host} while waiting for the Wi-Fi")
                continue
            stopped.wait(1)
        if stopped.is_set():
            raise InterruptedError("Service stopping")
        status.pop("warning", None)
        mark(f"Wi-Fi {network['ssid']} up on channel {network['channel']}")
        address = network["address"]
        platform.interface, platform.ap_interface = network["device"], network["ifname"]
        host = str(address.ip)
        base_warning = lan_warning(address)
        if base_warning:
            say(f"warning: LAN {address} is outside 100.64.0.0/10")
        renewed = ensure_keystore(state)
        status.update(ssid=network["ssid"], home=f"http://{host}:{SETTINGS_PORT}/",
                      entries=[f"https://{name}:{viewer}/", f"https://{host}:{viewer}/"])
        if ddns:
            maintainer.append(own_domain.Maintainer(root, ddns, host, stopped, say, tesla=True))
            maintainer[0].start()
        refresh_network_warning(network["device"], status, base_warning)
        trusted[:] = trusted_networks(network)
        if not settings_open:
            settings.start(SETTINGS_PORT)
        # The Tesla's connectivity checks are answered for as long as the box runs (D4): the LAN never flips
        # with the SIM's signal, only the upstream status text does.
        offline_checks.start(network, name, SETTINGS_PORT, status)
        diagnostics.start(stopped, diagnostics.DiagLog(state / "diag"), RUN / "receiver.log", platform, status,
                          state=state)
        # A new release is looked for once a day and only shown (LuCI, settings page); nothing installs by itself.
        threading.Thread(target=update.checker, args=(root, stopped, config["update_check"] != "0"),
                         name="update-check", daemon=True).start()

        bluetooth_thread.join()
        wireless = bool(bluetooth and bluetooth[0])
        status["bluetooth"] = wireless
        if have_identity:
            # A renewed certificate needs a new receiver: it reads the keystore once (audit A6).
            if early and plan_of(early) == plan_of(network) and wireless and not renewed:
                mark("early receiver kept")
            else:
                if early:
                    platform.stop_child("receiver", timeout=40)
                    mark("early receiver stopped: the live Wi-Fi, Bluetooth or certificate differs")
                launch(network, wireless)
        else:
            say("MFi identity missing: settings page only, CarPlay starts once the files are added")
        say(f"DashPlay services started on {network['ssid']} ({host}, channel {network['channel']})")
        plan = plan_of(network)
        next_check = time.monotonic() + RECHECK_EVERY
        while not stopped.wait(2):
            if not have_identity and identity_ok():
                request_reexec("MFi identity added")
                continue
            for child_name, child in platform.children:
                if child_name == 'tesla-dns-log':
                    continue  # optional diagnostic collector is retried by OfflineChecks
                if child.poll() is not None:
                    raise RuntimeError(f"{child_name} exited with {child.returncode}")
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + RECHECK_EVERY
                offline_checks.refresh(status)
                refresh_network_warning(network["device"], status, base_warning)
                now, why = platform.handoff()
                if now is None or plan_of(now) != plan:
                    request_reexec("Wi-Fi changed" if now else why)
    except InterruptedError:
        pass
    finally:
        stopped.set()
        for worker in maintainer:
            worker.join(10)   # acme.sh is stopped first: no signer left running into the restarted service
        offline_checks.restore()
        settings.stop()
        platform.stop_all()
        say("DashPlay services stopped")
    if reexec and reexec[0] is not None:
        say(f"restarting: {reexec[0]}")
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), "--root", str(root)])


if __name__ == "__main__":
    main()
