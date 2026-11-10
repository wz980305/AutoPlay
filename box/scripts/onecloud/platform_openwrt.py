"""OpenWrt adapter: the router owns the network (netifd, uci); AutoPlay only reads it.

The person sets up Wi-Fi in LuCI as usual. AutoPlay hands the iPhone one of the router's own access points
over Bluetooth (5 GHz first) and serves the viewer on that network's address. Nothing here creates hotspots
or joins networks.

No operations run at import time; the parsers take command output so they are testable anywhere.
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import subprocess

RUN = Path("/var/run/autoplay")
BLUETOOTH_NAME = "AutoPlay"   # what iPhones list under Bluetooth (bluetoothctl system-alias)


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def _number(pattern, text, cast=float):
    match = re.search(pattern, text, re.M)
    return cast(match.group(1)) if match else None


def parse_stations(text):
    """`iw dev X station dump`: per peer signal, bit rates and cumulative retries/failures."""
    peers = []
    for block in re.split(r"^Station ", text, flags=re.M)[1:]:
        peers.append({"peer": block.split()[0][-5:],
                      "signal": _number(r"^\s*signal:\s*(-?\d+)", block, int),
                      "rx_mbps": _number(r"rx bitrate:\s*([\d.]+)", block),
                      "tx_mbps": _number(r"tx bitrate:\s*([\d.]+)", block),
                      "tx_packets": _number(r"tx packets:\s*(\d+)", block, int),
                      "tx_retries": _number(r"tx retries:\s*(\d+)", block, int),
                      "tx_failed": _number(r"tx failed:\s*(\d+)", block, int),
                      "inactive_ms": _number(r"inactive time:\s*(\d+)", block, int)})
    return peers


def _ubus(path, method="status"):
    """`ubus call path method` as a dict; {} when it fails or hangs: netifd may not answer for a while (an
    interface it cannot set up took 30 s in the OpenWrt container, 2026-10-19), which must not end the service."""
    try:
        out = subprocess.run(["ubus", "call", path, method], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    try:
        return json.loads(out.stdout or "{}")
    except ValueError:
        return {}


def handoff_security(encryption):
    """uci wireless encryption -> what the receiver tells the iPhone; None when it cannot be handed over.
    WPA2/WPA3 transition goes out as WPA2: with "WPA3 transition" the iPhone accepted the handoff but
    never joined (OneCloud, 2026-10-11)."""
    value = (encryption or "none").split("+")[0]
    if value == "none":
        return "open"
    if value in ("psk", "psk2", "psk-mixed", "sae-mixed"):
        return "wpa2"
    if value == "sae":
        return "wpa3"
    return None   # enterprise (wpa, wpa2, wpa3...) and owe: the iPhone cannot be handed these


def wifi_networks(status):
    """`ubus call network.wireless status` -> the configured Wi-Fi networks, up ones first, 5 GHz first."""
    found = []
    for radio, data in sorted((status or {}).items()):
        config = data.get("config") or {}
        band = config.get("band") or ("5g" if str(config.get("channel", "")).isdigit()
                                     and int(config["channel"]) > 14 else "2g")
        for entry in data.get("interfaces") or []:
            iface = entry.get("config") or {}
            networks = iface.get("network") or []
            if isinstance(networks, str):
                networks = networks.split()
            found.append({
                "section": entry.get("section", ""), "ifname": entry.get("ifname", ""), "radio": radio,
                "up": bool(data.get("up")) and bool(entry.get("ifname")), "band": band,
                "mode": iface.get("mode", ""), "ssid": iface.get("ssid", ""), "key": iface.get("key", ""),
                "encryption": iface.get("encryption", "none"), "network": networks[0] if networks else "",
                "channel": config.get("channel", ""),
            })
    rank = {"5g": 0, "6g": 1, "2g": 2}
    return sorted(found, key=lambda n: (not n["up"], n["mode"] != "ap", rank.get(n["band"], 3)))


def pick_network(networks, live=True):
    """The network to hand the iPhone: the first usable access point (5 GHz preferred). The F50 cannot be a
    client and an access point at once, so client networks are never candidates (tesla_only_box_delta.md D10).
    Returns (network, reason when none fits)."""
    candidates = [n for n in networks if n["mode"] == "ap"]
    if not candidates:
        return None, "no Wi-Fi network is switched on (access point)"
    usable = [n for n in candidates if handoff_security(n["encryption"]) and n["ssid"]]
    if not usable:
        return None, "no Wi-Fi network with a password type the iPhone accepts (open, WPA2 or WPA3 personal)"
    up = [n for n in usable if (n["up"] or not live) and n["network"]]
    if not up:
        return None, f"Wi-Fi {usable[0]['ssid']} is not up yet"
    return up[0], ""


def parse_channel(iw_info):
    match = re.search(r"\bchannel (\d+)", iw_info or "")
    return int(match.group(1)) if match else None


def interface_address(status):
    """`ubus call network.interface.<name> status` -> (layer-3 device, IPv4 interface) or (None, None)."""
    addresses = (status or {}).get("ipv4-address") or []
    if not status or not status.get("up") or not addresses:
        return None, None
    first = addresses[0]
    return status.get("l3_device") or status.get("device"), ipaddress.IPv4Interface(
        f"{first['address']}/{first.get('mask', 32)}")


def hottest(zones=Path("/sys/class/thermal")):
    """The hottest readable thermal zone in degrees C, for the drive log (the F50 has some 25, a few unreadable)."""
    temps = []
    for zone in zones.glob("thermal_zone*"):
        try:
            temps.append(int((zone / "temp").read_text().strip()))
        except (OSError, ValueError):
            pass
    return round(max(temps) / 1000, 1) if temps else None


def thermal(zones=Path("/sys/class/thermal")):
    """What is hot and whether the kernel is holding the CPU back (1.4.3; the drive of 2026-11-10 reached 71.9 C with
    only "the hottest zone" recorded, so the chip, the 5G modem and the charger could not be told apart).
    temps: every readable zone by its name without the "-thmzone" ending, whole degrees, an unnamed zone as zoneN;
    throttle: only cooling devices whose state is not 0, as "state/max"."""
    temps, throttle = {}, {}
    for zone in sorted(zones.glob("thermal_zone*")):
        try:
            value = int((zone / "temp").read_text().strip())
        except (OSError, ValueError):
            continue
        try:
            name = (zone / "type").read_text().strip().removesuffix("-thmzone") or zone.name[8:]
        except OSError:
            name = zone.name[8:]
        temps[name if name not in temps else f"{name}.{zone.name[12:]}"] = round(value / 1000)
    for device in sorted(zones.glob("cooling_device*")):
        try:
            state = int((device / "cur_state").read_text().strip())
            if state:
                throttle[(device / "type").read_text().strip().removeprefix("thermal-")] = \
                    f"{state}/{(device / 'max_state').read_text().strip()}"
        except (OSError, ValueError):
            continue
    return temps, throttle


def cpu_mhz(cpus=Path("/sys/devices/system/cpu/cpufreq")):
    """Each frequency cluster's current and allowed-maximum MHz, "1703/2301": a maximum below the hardware's is the
    thermal cap or a saving profile at work."""
    result = []
    for policy in sorted(cpus.glob("policy*"), key=lambda path: int(path.name[6:] or 0)):
        try:
            result.append(f"{int((policy / 'scaling_cur_freq').read_text()) // 1000}"
                          f"/{int((policy / 'scaling_max_freq').read_text()) // 1000}")
        except (OSError, ValueError):
            continue
    return result


def neighbours(arp=Path("/proc/net/arp"), leases=Path("/tmp/dhcp.leases")):
    """MAC -> {"ip", "name"} of what the box talks to: the kernel's neighbour table and dnsmasq's leases. The F50's
    Wi-Fi firmware reports no signal or counters per client (mu300-linux FINDINGS 180), so who each station is, is
    what there is to say about it."""
    found = {}
    try:
        for line in arp.read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 6 and fields[2] != "0x0":
                found[fields[3].lower()] = {"ip": fields[0]}
    except OSError:
        pass
    try:
        for line in leases.read_text().splitlines():
            fields = line.split()
            if len(fields) >= 4:
                entry = found.setdefault(fields[1].lower(), {"ip": fields[2]})
                if fields[3] != "*":
                    entry["name"] = fields[3][:32]
    except OSError:
        pass
    return found


def stations(text, known):
    """`iw dev X station dump` as the drive log keeps it: only what the driver did report (the F50: the address
    alone, eight nulls a station before 1.4.3), with the station's address on the LAN and its DHCP name."""
    peers = []
    for block, peer in zip(re.split(r"^Station ", text, flags=re.M)[1:], parse_stations(text)):
        entry = {key: value for key, value in peer.items() if value is not None}
        entry.update(known.get(block.split()[0].lower(), {}))
        peers.append(entry)
    return peers


class OpenWrtPlatform:
    """Child processes, the Bluetooth adapter and the Wi-Fi read from OpenWrt. Standalone: the process and
    Bluetooth handling used to be inherited from DebianPlatform (code_inventory_trimming.md 2.1)."""

    def __init__(self, interface="", run=RUN):
        self.interface, self.run = interface, Path(run)
        self.ap_interface = interface   # the access point handed to the iPhone, once known
        self.children = []
        self.bluetooth_state = None     # state/ directory, set by the supervisor

    boot_id = staticmethod(boot_id)

    def start(self, name, argv):
        """Start a child in its own session with its stdout/stderr in RUN/<name>.log."""
        with (self.run / (name + ".log")).open("w") as log:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        self.children.append((name, child))
        return child

    def child(self, name):
        return next((child for child_name, child in self.children if child_name == name), None)

    def stop_child(self, name, timeout=8):
        for entry in list(self.children):
            if entry[0] == name:
                self.children.remove(entry)
                if entry[1].poll() is None:
                    os.killpg(entry[1].pid, signal.SIGTERM)
                    try:
                        entry[1].wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        os.killpg(entry[1].pid, signal.SIGKILL)
                        entry[1].wait()

    def forget_child(self, name):
        """Drop an exited child from the list (its restart is the supervisor's business)."""
        self.children = [entry for entry in self.children if entry[0] != name]

    def stop_all(self):
        for name, child in reversed(self.children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    # The JVM writes its AppCDS archive while exiting; that took longer than 8 s here. The F50's
                    # Bluetooth helper stops its own children within 6 s (board_zte_f50.py).
                    child.wait(timeout={"receiver": 40, "bluetooth": 15}.get(name, 8))
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        self.children = []

    @staticmethod
    def bluetooth_bus_ready():
        """The board helper's own D-Bus socket (DBUS_SYSTEM_BUS_ADDRESS) appears a few seconds into the boot;
        bluetoothctl segfaults until it is there (2026-10-16), so callers wait for the socket instead of running it."""
        bus = os.environ.get("DBUS_SYSTEM_BUS_ADDRESS", "")
        if bus.startswith("unix:path="):
            return os.path.exists(bus[len("unix:path="):].split(",", 1)[0])
        return True

    def power_bluetooth(self):
        """Power the adapter on and name it; False while bluetoothd is not ready. The address is the board
        helper's business (mu300-bt-init at btattach), so there is no btmgmt identity step here."""
        if not self.bluetooth_bus_ready():
            return False
        if subprocess.run(["bluetoothctl", "power", "on"], capture_output=True, timeout=10).returncode != 0:
            return False
        # A phone link left over from the previous run (service restart, network rebuild) fails every
        # invitation with br-connection-already-connected until the bridge's rate-limited recovery
        # power-cycles the adapter (2026-10-11: 69 s). Nothing uses Bluetooth yet, so clear it now.
        connected = subprocess.run(["bluetoothctl", "devices", "Connected"], capture_output=True, text=True, timeout=10)
        if connected.stdout.lstrip().startswith("Device "):
            subprocess.run(["bluetoothctl", "power", "off"], capture_output=True, timeout=10)
            if subprocess.run(["bluetoothctl", "power", "on"], capture_output=True, timeout=10).returncode != 0:
                return False
        # BlueZ names the adapter after the host, which is what iPhones list under Bluetooth. Set on every
        # start: a reset or a fresh image clears BlueZ's stored alias.
        subprocess.run(["bluetoothctl", "system-alias", BLUETOOTH_NAME], capture_output=True, timeout=10)
        return True

    def handoff(self, live=True):
        """(network dict with channel, address and device, reason when not ready).
        live=False: what the configuration says before the radio is up (the access point's configured
        channel, the LAN address), so that the receiver can start while the Wi-Fi comes up."""
        network, reason = pick_network(wifi_networks(_ubus("network.wireless")), live)
        if not network:
            return None, reason
        device, address = interface_address(_ubus(f"network.interface.{network['network']}"))
        if not address:
            return None, f"network {network['network']} for Wi-Fi {network['ssid']} has no IPv4 address yet"
        info = subprocess.run(["iw", "dev", network["ifname"], "info"], capture_output=True, text=True,
                              timeout=5).stdout if live and network["ifname"] else ""
        channel = parse_channel(info) or (int(network["channel"]) if str(network["channel"]).isdigit() else None)
        if not channel:
            return None, f"Wi-Fi {network['ssid']} has no channel yet"
        return dict(network, channel=channel, address=address, device=device,
                    security=handoff_security(network["encryption"])), ""

    @staticmethod
    def interface_network(name):
        """The IPv4 address of netifd interface `name` (e.g. the LAN), or None."""
        return interface_address(_ubus(f"network.interface.{name}"))[1]

    def diagnostics(self):
        data = {}
        try:
            data["load"] = float(Path("/proc/loadavg").read_text().split()[0])
            meminfo = Path("/proc/meminfo").read_text()
            data["mem_mb"] = int(re.search(r"^MemAvailable:\s*(\d+)", meminfo, re.M).group(1)) // 1024
        except (OSError, ValueError, AttributeError):
            pass
        temp = hottest()
        if temp is not None:
            data["temp_c"] = temp
        temps, throttle = thermal()
        if temps:
            data["temps"] = temps
        if throttle:
            data["throttle"] = throttle
        frequencies = cpu_mhz()
        if frequencies:
            data["cpu_mhz"] = frequencies
        if self.ap_interface:
            data["peers"] = stations(subprocess.run(["iw", "dev", self.ap_interface, "station", "dump"],
                                                    capture_output=True, text=True, timeout=5).stdout, neighbours())
        return data
