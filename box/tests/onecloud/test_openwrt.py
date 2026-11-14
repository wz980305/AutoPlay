"""OpenWrt adapter: Wi-Fi chosen from ubus/uci output, settings page without network setup."""
import ipaddress
import json
import re
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import platform_openwrt as ow
from settings_page import SettingsPage
import supervisor_openwrt
from supervisor_openwrt import (read_config, trusted_networks, shared_lan_conflict, waiting_trust, waiting_warning,
                               obsolete_options, legacy_dns_cleanup, lan_warning, box_name, receiver_command,
                               SETTINGS_PORT, OBSOLETE_OPTIONS, DEFAULTS)


class ViewerPortConfigTests(unittest.TestCase):
    def test_default_is_empty(self):
        # Empty lets the supervisor adopt an owner's older state/receiver/config.json port; 18443 is the fallback.
        self.assertEqual(read_config("")["viewer_port"], "")

    def test_parsed(self):
        self.assertEqual(read_config("autoplay.main.viewer_port='19000'")["viewer_port"], "19000")

# Shape of `ubus call network.wireless status` on OpenWrt 25.12 (two radios, a 2.4 GHz AP listed first).
WIRELESS = {
    "radio0": {"up": True, "config": {"band": "2g", "channel": "1"}, "interfaces": [
        {"section": "default_radio0", "ifname": "phy0-ap0",
         "config": {"mode": "ap", "ssid": "Home-2G", "encryption": "psk2", "key": "secret-2g", "network": ["lan"]}}]},
    "radio1": {"up": True, "config": {"band": "5g", "channel": "auto"}, "interfaces": [
        {"section": "default_radio1", "ifname": "phy1-ap0",
         "config": {"mode": "ap", "ssid": "Car-5G", "encryption": "sae-mixed", "key": "secret-5g", "network": ["lan"]}},
        {"section": "wwan", "ifname": "phy1-sta0",
         "config": {"mode": "sta", "ssid": "Xpeng", "encryption": "psk2", "key": "car-pass", "network": ["wwan"]}}]},
}
LAN = {"up": True, "l3_device": "br-lan", "ipv4-address": [{"address": "192.168.1.1", "mask": 24}]}


class HandoffTests(unittest.TestCase):
    def test_security_types_the_iphone_can_be_handed(self):
        self.assertEqual(ow.handoff_security("none"), "open")
        self.assertEqual(ow.handoff_security("psk2+ccmp"), "wpa2")
        self.assertEqual(ow.handoff_security("psk-mixed"), "wpa2")
        self.assertEqual(ow.handoff_security("sae-mixed"), "wpa2")   # transition is announced as WPA2
        self.assertEqual(ow.handoff_security("sae"), "wpa3")
        for enterprise in ("wpa2", "wpa3", "wpa-mixed", "owe"):
            self.assertIsNone(ow.handoff_security(enterprise))

    def test_auto_prefers_an_up_5ghz_access_point(self):
        network, reason = ow.pick_network(ow.wifi_networks(WIRELESS))
        self.assertEqual((network["ssid"], network["ifname"], network["network"]), ("Car-5G", "phy1-ap0", "lan"))
        self.assertEqual(reason, "")

    def test_client_networks_are_never_candidates(self):
        # The F50 cannot be a client and an access point at once (tesla_only_box_delta.md D10).
        only_sta = {radio: dict(data, interfaces=[i for i in data["interfaces"] if i["config"]["mode"] == "sta"])
                    for radio, data in WIRELESS.items()}
        network, reason = ow.pick_network(ow.wifi_networks(only_sta))
        self.assertIsNone(network)
        self.assertEqual(reason, "no Wi-Fi network is switched on (access point)")

    def test_waits_while_the_radio_is_down_and_skips_enterprise(self):
        down = json.loads(json.dumps(WIRELESS))
        for radio in down.values():
            radio["up"] = False
        network, reason = ow.pick_network(ow.wifi_networks(down))
        self.assertIsNone(network)
        self.assertIn("is not up yet", reason)
        enterprise = {"radio0": {"up": True, "config": {"band": "5g"}, "interfaces": [
            {"section": "x", "ifname": "phy0-ap0", "config": {"mode": "ap", "ssid": "Corp", "encryption": "wpa2",
                                                               "network": ["lan"]}}]}}
        self.assertIn("password type", ow.pick_network(ow.wifi_networks(enterprise))[1])

    def test_channel_and_address_parsing(self):
        self.assertEqual(ow.parse_channel("Interface phy1-ap0\n\tchannel 149 (5745 MHz), width: 80 MHz"), 149)
        self.assertIsNone(ow.parse_channel("Interface phy1-ap0\n\ttype AP"))
        self.assertEqual(ow.interface_address(LAN), ("br-lan", ipaddress.IPv4Interface("192.168.1.1/24")))
        self.assertEqual(ow.interface_address({"up": False}), (None, None))

    def test_handoff_reads_ubus_and_the_live_channel(self):
        calls = {"network.wireless": WIRELESS, "network.interface.lan": LAN}

        class Done:
            def __init__(self, stdout): self.stdout, self.returncode = stdout, 0

        def run(argv, **_):
            if argv[0] == "ubus":
                return Done(json.dumps(calls.get(argv[2], {})))
            return Done("Interface phy1-ap0\n\tchannel 36 (5180 MHz), width: 80 MHz")

        with tempfile.TemporaryDirectory() as tmp, patch.object(ow.subprocess, "run", run):
            network, reason = ow.OpenWrtPlatform(run=Path(tmp)).handoff()
        self.assertEqual(reason, "")
        self.assertEqual((network["channel"], network["security"], network["device"], str(network["address"].ip)),
                         (36, "wpa2", "br-lan", "192.168.1.1"))





class TemperatureTests(unittest.TestCase):
    def test_the_drive_log_takes_the_hottest_readable_zone(self):
        # F50, 2026-10-19: the drive log had no temperature; its zones are named (soc, nr, pa), two cannot be read.
        with tempfile.TemporaryDirectory() as tmp:
            for name, value in (("thermal_zone0", "33987\n"), ("thermal_zone1", "36670\n"), ("thermal_zone2", "")):
                (Path(tmp) / name).mkdir()
                (Path(tmp) / name / "temp").write_text(value)
            (Path(tmp) / "thermal_zone3").mkdir()
            self.assertEqual(ow.hottest(Path(tmp)), 36.7)
            self.assertIsNone(ow.hottest(Path(tmp) / "none"))

    def test_how_busy_the_processors_were_and_what_kept_them_busy(self):
        # 2026-11-10: the load average said 4 with CarPlay and without, which told nothing about AutoPlay's share.
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            def write(total_idle, tasks):
                (proc / "stat").write_text(f"cpu  {total_idle[0]} 0 0 {total_idle[1]} 0 0 0 0 0 0\ncpu0 1 2 3\n")
                for pid, (name, ticks) in tasks.items():
                    (proc / pid).mkdir(exist_ok=True)
                    (proc / pid / "stat").write_text(f"{pid} ({name}) S 1 1 1 0 -1 4194560 10 0 0 0 {ticks} 0 0 0 20 0 1 0 100 0 0\n")
            (proc / "self").mkdir()
            meter = ow.CpuMeter(proc)
            write((1000, 9000), {"10": ("java", 500), "11": ("java", 100), "12": ("kworker/0:1 (x)", 50), "13": ("python3", 70)})
            self.assertIsNone(meter.sample(), "nothing to compare with yet")
            write((1200, 9800), {"10": ("java", 600), "11": ("java", 140), "12": ("kworker/0:1 (x)", 60), "14": ("sh", 900)})
            self.assertEqual(meter.sample(), {"busy": 20, "top": [["java", 14.0], ["kworker/0:1 (x)", 1.0]]},
                             "a program's processes together; one that just started or ended is left out")
            self.assertIsNone(meter.sample(), "no time passed")
            self.assertIsNone(ow.CpuMeter(proc / "none").sample())

    def test_each_zone_by_name_and_only_the_cooling_that_is_at_work(self):
        # 2026-11-10: 71.9 C at the worst drop, and no way to tell the chip from the modem or the charger.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, kind, value in (("thermal_zone0", "soc-thmzone", "70421"), ("thermal_zone1", "nr-thmzone", "48100"),
                                      ("thermal_zone2", "pa-thmzone", ""), ("thermal_zone3", None, "39000")):
                (root / name).mkdir()
                (root / name / "temp").write_text(value)
                if kind:
                    (root / name / "type").write_text(kind + "\n")
            for name, kind, state in (("cooling_device0", "thermal-cpufreq-0", "2"), ("cooling_device1", "thermal-cpu-0", "0")):
                (root / name).mkdir()
                (root / name / "type").write_text(kind + "\n")
                (root / name / "cur_state").write_text(state + "\n")
                (root / name / "max_state").write_text("9\n")
            self.assertEqual(ow.thermal(root), ({"soc": 70, "nr": 48, "zone3": 39}, {"cpufreq-0": "2/9"}))
            self.assertEqual(ow.thermal(root / "none"), ({}, {}))
            for policy, now, top in (("policy0", "1228800", "1228800"), ("policy4", "1703000", "2301000")):
                (root / policy).mkdir()
                (root / policy / "scaling_cur_freq").write_text(now + "\n")
                (root / policy / "scaling_max_freq").write_text(top + "\n")
            self.assertEqual(ow.cpu_mhz(root), ["1228/1228", "1703/2301"])


class TrustedNetworkTests(unittest.TestCase):
    def test_only_the_network_of_the_wifi_handed_to_the_iphone(self):
        # Every interface used to count, the WAN too (F50: sipa_eth0 10.3.178.29/8, the whole 10/8);
        # only the firewall kept it out (audit 2026-10-13, A5).
        lan = {"network": "lan", "address": ipaddress.IPv4Interface("192.168.77.1/24")}
        self.assertEqual(trusted_networks(lan), [ipaddress.IPv4Network("192.168.77.0/24")])
        self.assertNotIn(ipaddress.ip_address("10.3.178.30"), trusted_networks(lan)[0])
        car = {"network": "wwan", "address": ipaddress.IPv4Interface("192.168.43.123/24")}
        self.assertEqual(trusted_networks(car), [ipaddress.IPv4Network("192.168.43.0/24")])


class WaitingForWifiTests(unittest.TestCase):
    # 2026-10-19 (momo): the F50's own Wi-Fi turned off, the settings page never opened while DashPlay waited for it.
    def test_the_settings_page_trusts_the_planned_wifi_or_else_the_lan(self):
        planned = {"address": ipaddress.IPv4Interface("192.168.77.1/24")}
        self.assertEqual(waiting_trust(planned, None), [ipaddress.IPv4Network("192.168.77.0/24")])
        self.assertEqual(waiting_trust(None, ipaddress.IPv4Interface("192.168.1.1/24")),
                         [ipaddress.IPv4Network("192.168.1.0/24")])
        self.assertEqual(waiting_trust(None, None), [])

    def test_a_switched_off_access_point_is_named_as_such(self):
        # A disabled wifi-iface is left out of `ubus call network.wireless status` altogether (F50, 2026-10-19).
        radio_only = {"radio0": {"up": True, "config": {"band": "5g", "channel": "149"}, "interfaces": []}}
        self.assertEqual(ow.pick_network(ow.wifi_networks(radio_only)),
                         (None, "no Wi-Fi network is switched on (access point)"))

    def test_the_page_says_what_it_waits_for(self):
        self.assertIn("尚未就绪：「DashPlay-F50」尚未开启。", waiting_warning("Wi-Fi DashPlay-F50 is not up yet"))
        self.assertIn("路由器的 Wi-Fi 均已关闭", waiting_warning("no Wi-Fi network is switched on (access point)"))
        self.assertIn("「Car-5G」所在的网络 lan 尚无地址",
                      waiting_warning("network lan for Wi-Fi Car-5G has no IPv4 address yet"))
        self.assertIn("the other router's Wi-Fi channel is missing",   # anything else as it is
                      waiting_warning("the other router's Wi-Fi channel is missing: set a fixed channel there and enter it"))

    def test_a_hanging_ubus_is_no_address(self):
        def hang(argv, **kwargs):
            raise ow.subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        with patch.object(ow.subprocess, "run", hang):
            self.assertIsNone(ow.OpenWrtPlatform.interface_network("lan"))
            self.assertEqual(ow._ubus("network.wireless"), {})

    def test_the_lan_address_comes_from_ubus(self):
        class Done:
            def __init__(self, stdout): self.stdout, self.returncode = stdout, 0

        with patch.object(ow.subprocess, "run", lambda argv, **_: Done(json.dumps(LAN if argv[2] == "network.interface.lan" else {}))):
            self.assertEqual(ow.OpenWrtPlatform.interface_network("lan"), ipaddress.IPv4Interface("192.168.1.1/24"))
            self.assertIsNone(ow.OpenWrtPlatform.interface_network("guest"))

DHCP = """dhcp.cfg01411c=dnsmasq
dhcp.cfg01411c.domain='lan'
dhcp.cfg01411c.local='/lan/'
dhcp.lan=dhcp
"""
NAME, LAN_IP, PUBLIC = "car.duckdns.org", "192.168.77.1", "2408:8409:8500:1d4:a00:1ff:fe00:1"


def applied(uci, changes):
    """The `uci show dhcp` that the changes leave behind (enough of uci for these records)."""
    lines = uci.splitlines()
    for change in changes:
        verb, arg = change[0], change[1] if len(change) > 1 else ""
        key, _, value = arg.partition("=")
        if verb == "set":
            lines = [l for l in lines if not l.startswith(key + "=")]
            lines.append(f"{key}={value}" if "." not in key[5:] else f"{key}='{value}'")
        elif verb == "delete":
            lines = [l for l in lines if not (l.startswith(key + "=") or l.startswith(key + "."))]
        elif verb in ("add_list", "del_list"):
            old = next((l for l in lines if l.startswith(key + "=")), None)
            values = re.findall(r"'([^']*)'", old) if old else []
            values = values + [value] if verb == "add_list" else [v for v in values if v != value]
            lines = [l for l in lines if l != old] + ([key + "=" + " ".join(f"'{v}'" for v in values)] if values else [])
    return "\n".join(lines) + "\n"


class LegacyCleanupTests(unittest.TestCase):
    """What older releases left in uci goes once (D2): own-name DNS records, rebind whitelist, obsolete options."""

    def test_nothing_to_do_on_a_clean_box(self):
        self.assertEqual(legacy_dns_cleanup(DHCP), [])
        self.assertEqual(obsolete_options("autoplay.main=autoplay\nautoplay.main.enabled='1'\n"), [])

    def test_old_name_records_and_whitelist_go(self):
        old = DHCP + (f"dhcp.dashplay=domain\ndhcp.dashplay.name='{NAME}'\ndhcp.dashplay.ip='{LAN_IP}'\n"
                      f"dhcp.dashplay6=domain\ndhcp.dashplay6.name='{NAME}'\ndhcp.dashplay6.ip='{PUBLIC}'\n"
                      f"dhcp.cfg01411c.server='/{NAME}/' '192.0.2.53'\n"
                      f"dhcp.cfg01411c.rebind_domain='/{NAME}/' '/other.example/'\n")
        changes = legacy_dns_cleanup(old)
        self.assertIn(["delete", "dhcp.dashplay"], changes)
        self.assertIn(["delete", "dhcp.dashplay6"], changes)
        self.assertIn(["del_list", f"dhcp.cfg01411c.server=/{NAME}/"], changes)
        self.assertIn(["del_list", f"dhcp.cfg01411c.rebind_domain=/{NAME}/"], changes)
        self.assertEqual(changes[-1], ["commit", "dhcp"])
        after = applied(old, changes)
        self.assertNotIn("autoplay", after)
        self.assertIn("'/other.example/'", after, "other programs' entries stay")
        self.assertIn("'192.0.2.53'", after)
        self.assertEqual(legacy_dns_cleanup(after), [])

    def test_obsolete_options_are_dropped_and_the_seven_keys_kept(self):
        old = ("autoplay.main=autoplay\nautoplay.main.enabled='1'\nautoplay.main.wifi='auto'\n"
               "autoplay.main.tesla_mode='1'\nautoplay.main.answer_tesla_checks='0'\nautoplay.main.settings_port='18080'\n"
               "autoplay.main.bluetooth_service='/usr/bin/python3 /opt/autoplay/board_zte_f50.py'\n"
               "autoplay.main.duckdns_domain='mycar'\nautoplay.main.idle_release='0'\n")
        changes = obsolete_options(old)
        self.assertEqual({c[1] for c in changes if c[0] == "delete"},
                         {"autoplay.main.wifi", "autoplay.main.tesla_mode", "autoplay.main.answer_tesla_checks",
                          "autoplay.main.settings_port", "autoplay.main.bluetooth_service"})
        self.assertEqual(changes[-1], ["commit", "autoplay"])
        config = read_config(old)
        self.assertEqual(set(config), set(DEFAULTS))
        self.assertEqual((config["duckdns_domain"], config["idle_release"]), ("mycar", "0"))
        self.assertFalse(set(DEFAULTS) & set(OBSOLETE_OPTIONS))


# `uci -q show network` and `ip -4 -o addr show` of the F50 (2026-10-14), without its Tailscale line.
NETWORK = """network.lan=interface
network.lan.device='br-lan'
network.lan.proto='static'
network.lan.ipaddr='192.168.77.1'
network.lan.ip6assign='60'
network.lan.netmask='255.255.255.0'
network.wan=interface
network.wan.proto='dhcp'
"""
ADDRESSES = """1: lo    inet 127.0.0.1/8 scope host lo
13: sipa_eth0    inet 10.123.116.156/8 scope global sipa_eth0
34: br-lan    inet 192.168.77.1/24 brd 192.168.77.255 scope global br-lan
"""


class SharedLanTests(unittest.TestCase):
    """The LAN is 100.96.0.1/24 from install time (D1); the service only warns (lan_warning, shared_lan_conflict)."""

    def test_the_lan_outside_the_shared_space_is_a_warning_not_a_move(self):
        self.assertEqual(lan_warning(ipaddress.IPv4Interface("100.96.0.1/24")), "")
        self.assertEqual(lan_warning(ipaddress.IPv4Interface("100.97.0.1/24")), "")
        self.assertIn("192.168.77.1/24", lan_warning(ipaddress.IPv4Interface("192.168.77.1/24")))
        self.assertIn("100.96.0.1/24", lan_warning(ipaddress.IPv4Interface("192.168.77.1/24")))
        self.assertEqual(lan_warning(None), "")
        self.assertFalse(hasattr(supervisor_openwrt, "apply_shared_lan"), "no run-time LAN move any more")

    def test_tailscale_or_an_overlapping_interface_warns(self):
        tailscale = ADDRESSES + "40: tailscale0    inet 100.64.5.6/32 scope global tailscale0\n"
        drop = 'chain ts-input { iifname != "tailscale0" ip saddr 100.64.0.0/10 counter packets 0 bytes 0 drop }\n'
        self.assertIn("Tailscale", shared_lan_conflict(tailscale, "br-lan", drop))
        self.assertIn("Tailscale", shared_lan_conflict(tailscale, "br-lan", None), "unreadable ruleset: assume the worst")
        self.assertEqual(shared_lan_conflict(tailscale, "br-lan", "table inet fw4 {}\n"), "", "netfilter-mode=off")
        mifi = ADDRESSES + "41: usb0    inet 100.96.0.50/24 scope global usb0\n"
        self.assertIn("usb0", shared_lan_conflict(mifi, "br-lan", ""))
        own = ADDRESSES.replace("192.168.77.1/24", "100.96.0.1/24")
        self.assertEqual(shared_lan_conflict(own, "br-lan", ""), "", "the LAN itself is no conflict")

    def test_the_warning_file_is_written_only_on_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "network-status.json"
            status = {}
            with patch.object(supervisor_openwrt.subprocess, "run") as run:
                run.return_value = supervisor_openwrt.subprocess.CompletedProcess([], 0, ADDRESSES, "")
                supervisor_openwrt.refresh_network_warning("br-lan", status, "", path)
                first = path.stat().st_mtime_ns
                time.sleep(0.01)
                supervisor_openwrt.refresh_network_warning("br-lan", status, "", path)
                self.assertEqual(path.stat().st_mtime_ns, first, "same text: not rewritten")
                supervisor_openwrt.refresh_network_warning("br-lan", status, "LAN wrong", path)
                self.assertNotEqual(path.stat().st_mtime_ns, first)
            self.assertEqual(json.loads(path.read_text())["warning"], "LAN wrong")


class ConfigTests(unittest.TestCase):
    def test_idle_release_defaults_to_five_minutes_and_can_be_turned_off(self):
        self.assertEqual(read_config("")["idle_release"], "300")
        self.assertEqual(read_config("autoplay.main.idle_release='0'\n")["idle_release"], "0")

    def test_eleven_keys_and_constants(self):
        # 7 keys of the Tesla-only trim (D-list) + the 4 of the DNSPod provider (1.0.0): anything else is a constant.
        # The audio route of 1.1.0-1.2.0 is gone (1.3.0, ADR-16) and is dropped from an upgraded box's config.
        self.assertEqual(sorted(DEFAULTS), ["dns_provider", "dnspod_id", "dnspod_token",
                                            "duckdns_domain", "duckdns_token", "enabled", "idle_release", "own_domain",
                                            "update_check", "update_mirror", "viewer_port"])
        self.assertIn("audio_route_navigation", supervisor_openwrt.OBSOLETE_OPTIONS)
        self.assertEqual(supervisor_openwrt.obsolete_options("autoplay.main.audio_route_navigation='bluetooth'\n"),
                         [["delete", "autoplay.main.audio_route_navigation"], ["commit", "autoplay"]])
        self.assertEqual(SETTINGS_PORT, 18080)
        self.assertEqual(str(supervisor_openwrt.SHARED_LAN), "100.96.0.1/24")
        self.assertEqual(supervisor_openwrt.JAVA, "/usr/lib/autoplay-jre/bin/java")

    def test_the_name_is_the_duckdns_one_or_the_local_one(self):
        self.assertEqual(box_name(None), "autoplay.lan")
        self.assertEqual(box_name({"domain": "mycar", "token": "x"}), "mycar.duckdns.org")

    def test_the_receiver_always_runs_in_tesla_mode(self):
        network = {"ssid": "Car-5G", "key": "k", "security": "wpa2", "channel": 149, "device": "br-lan",
                   "address": ipaddress.IPv4Interface("100.96.0.1/24")}
        command = receiver_command(Path("/opt/autoplay"), network, Path("/var/run/autoplay/handoff.json"), 18443, 300)
        self.assertIn("--tesla", command)
        self.assertNotIn("--car-music", command)
        self.assertNotIn("--no-wireless", command)
        self.assertEqual(command[command.index("--settings-port") + 1], "18080")
        self.assertEqual(command[command.index("--java") + 1], supervisor_openwrt.JAVA)
        self.assertIn("--no-wireless", receiver_command(Path("/x"), network, Path("/h"), 18443, 300, wireless=False))
        self.assertIn("--bind-wait", receiver_command(Path("/x"), network, Path("/h"), 18443, 300, wait=True))
        # No audio route any more (1.3.0): run-receiver.py itself passes the Bluetooth flags to the JVM.
        self.assertNotIn("--audio-route-navigation", command)

    def test_uci_options_override_defaults_and_unknown_keys_are_ignored(self):
        config = read_config("autoplay.main=autoplay\nautoplay.main.viewer_port='19000'\nautoplay.main.wifi='wwan'\n")
        self.assertEqual(config["viewer_port"], "19000")
        self.assertNotIn("wifi", config)


class ManagedPageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"; self.state.mkdir()
        self.status = {"mode": "openwrt", "ssid": "Car-5G", "home": "http://192.168.1.1:18080/", "identity": True,
                       "entries": ["https://dashplay.lan:18443/", "https://192.168.1.1:18443/"]}
        self.page = SettingsPage(self.state, lambda: self.status, lambda reason: None, lambda: [])

    def test_shows_phones_and_router_wifi_without_network_setup(self):
        html = self.page.render("")
        # What is on screen, not the style sheet's comments; "Wi-Fi" keeps its hyphen from breaking, addresses break
        # before the port (1.4.1).
        shown = html.split("</style>", 1)[1].replace("\u2011", "-").replace("<wbr>", "")
        for text in ("AutoPlay 热点", "Car-5G", "在 OpenWrt 后台设置", "https://dashplay.lan:18443/",
                     "添加"):
            self.assertIn(text, shown)
        self.assertIn("<div class=name>Car\u20115G</div>", html, "a name is not broken at its hyphen")
        self.assertIn("https://dashplay.lan<wbr>:18443/", html)
        for text in ("盒子热点", "重新进行首次设置", "使用方式", "第 1 步", "数据线", "用户名 root", "密码 1234", "组合与验证状态"):
            self.assertNotIn(text, html)
        # The settings page runs on 18080; a relative link stayed there and got a 404 (review 2026-10-12).
        self.assertIn('href="http://192.168.1.1/cgi-bin/luci/admin/network/wireless"', html)

    def test_network_changes_are_refused(self):
        nonce = self.page.pairing.nonce
        for path in ("/setup", "/reset", "/car", "/hotspot", "/retry"):
            with self.assertRaises(ValueError):
                self.page.apply(path, {"nonce": nonce})

    def test_the_box_temperature_and_an_alert_only_while_it_is_slowed_for_heat(self):
        # 2026-11-10: 72 C in a parked car, and the page had nothing to say about it.
        html = self.page.render("")
        self.assertNotIn("盒子温度", html, "no sensor, no row")
        self.page.thermal = lambda: ({"soc": 63, "nr": 48}, {})
        html = self.page.render("")
        self.assertIn("<b>盒子温度</b></span><span class=value>63 °C</span>", html)
        self.assertNotIn("过热", html)
        self.page.thermal = lambda: ({"soc": 74, "nr": 55}, {"devfreq-0": "1/2"})
        self.assertNotIn("过热", self.page.render(""), "the processor's own cooling is what counts")
        self.page.thermal = lambda: ({"soc": 74, "nr": 55}, {"cpufreq-0": "2/9"})
        html = self.page.render("")
        self.assertIn("盒子温度已达 74 °C，正在降速", html)
        self.assertIn("<span>过热，正在降速</span></span><span class=value>74 °C</span>", html)
        def broken(): raise OSError("sensor")
        self.page.thermal = broken
        self.assertNotIn("盒子温度", self.page.render(""))

    def test_the_daily_check_is_shown_with_the_update_button(self):
        import update
        update.save(self.state / "update-check.json", {"checked_at": 1, "current": "2026.10.19.1", "latest": "2026.10.20",
                                                       "notes": "- 新功能<b>\n- 修复", "available": True, "online": True})
        html = self.page.render("")
        for text in ("程序更新", "有新版本 2026.10.20", "- 新功能&lt;b&gt;<br>- 修复", "立即升级", "检查更新",
                     # the notes a tap away, as a row of their own (1.5.4: a small link)
                     '<a class=cell href="https://github.com/wz980305/AutoPlay/releases/tag/v2026.10.20"><span class="tile gray">',
                     '<b>完整更新说明</b></span><span class=chev></span></a>',
                     # this box's version is the row above the new one (1.5.0; a line "当前 …" inside it before)
                     "<b>本机程序</b></span><span class=value>2026.10.19.1</span>",
                     # and the category carries a numbered badge while there is something to install (1.5.4: a red
                     # dot, colour alone)
                     '<a href="#update">更新<i>1</i></a>'):
            self.assertIn(text, html)
        # 1.5.0: no standing line under the group; a footer speaks only while something is happening
        self.assertNotIn("每天自动检查", html)
        self.assertNotIn("<p class=foot>", html)
        # A CHANGELOG section as the notes: its opening paragraph, without Markdown marks (1.4.1).
        update.save(self.state / "update-check.json", {
            "checked_at": 1, "current": "1.4.0", "latest": "1.4.1", "available": True, "online": True,
            "notes": "无线断开后**自动邀请一次**，\n`触控`最后一个点。\n\n- **投屏页**：很长的细节……\n- 测试：……"})
        html = self.page.render("")
        self.assertIn("<span class=clamp>无线断开后自动邀请一次，<br>触控最后一个点。</span>", html)
        self.assertNotIn("很长的细节", html)
        update.save(self.state / "update-check.json", {"checked_at": 1, "latest": "2026.10.20", "available": True,
                                                       "online": False})
        html = self.page.render("")
        self.assertIn("需要按发布说明手动升级", html)
        self.assertNotIn("立即升级", html, "a release that changed the system is not offered online")
        update.save(self.state / "update-check.json", {"checked_at": 1, "current": "2026.10.20", "latest": "2026.10.20",
                                                       "available": False, "online": True})
        html = self.page.render("")
        self.assertIn("<b>已是最新</b></span><span class=value>2026.10.20</span>", html)
        self.assertNotIn("本机程序", html, "one row says both: the version and that none is newer")
        self.assertNotIn("<i></i>", html, "nothing to install, no dot")
        (self.state.parent / "version.txt").write_text("2026.10.21\n")
        self.assertIn("<b>已是最新</b></span><span class=value>2026.10.21</span>", self.page.render(""),
                      "the version is what this box runs")
        (self.state / "update-check.json").unlink()
        self.assertIn("<b>本机程序</b></span><span class=value>2026.10.21", self.page.render(""), "never checked")

    def test_a_failed_update_is_not_shown_once_the_box_is_up_to_date(self):
        # F50, 2026-10-19: updated by hand after a failed web update, the page still said it did not finish.
        import time
        import update
        update.save(self.state / "update-status.json", {"phase": "failed", "message": "下载失败", "at": time.time()})
        update.save(self.state / "update-check.json", {"checked_at": 1, "current": "2026.10.19.1", "latest": "2026.10.20",
                                                       "available": True, "online": True})
        self.assertIn("上次升级未完成", self.page.render(""))
        update.save(self.state / "update-check.json", {"checked_at": time.time() + 1, "current": "2026.10.20",
                                                       "latest": "2026.10.20",
                                                       "available": False, "online": True})
        html = self.page.render("")
        self.assertNotIn("上次升级未完成", html)
        self.assertIn("已是最新", html)

    def test_update_actions_need_the_page_and_start_apart(self):
        import update
        nonce = self.page.pairing.nonce
        with self.assertRaises(ValueError):
            self.page.apply("/update", {"action": "install", "nonce": "stale"})
        import threading
        release = threading.Event()
        with patch.object(update, "launch", return_value="已开始升级") as launch, \
                patch.object(update, "check", side_effect=lambda root: release.wait(5)) as check:
            # Started at once (1.5.4; 1.2.0 asked first): nothing to say at the top, the group shows it running (1.4.1).
            self.assertEqual(self.page.apply("/update", {"action": "install", "nonce": nonce}), "")
            launch.assert_called_once_with(self.state.parent)
            # Checking: no banner asking to reload; the group says "checking" and the page refreshes itself (1.4.1).
            self.assertEqual(self.page.apply("/update", {"action": "check", "nonce": nonce}), "")
            html = self.page.render("")
            self.assertIn("正在检查更新…", html)
            self.assertIn("http-equiv=refresh content=2", html)
            self.assertNotIn('class="banner', html)
            self.assertNotIn("value=check>检查更新", html, "no second check while one runs")
            self.page.apply("/update", {"action": "check", "nonce": nonce})
            release.set()
            for _ in range(100):
                if not self.page.check_running():
                    break
                time.sleep(.02)
            self.assertEqual(check.call_count, 1, "one check at a time")
            self.assertNotIn("正在检查更新", self.page.render(""))
        # Refused (CarPlay in use): said in the update group, not at the top.
        with patch.object(update, "launch", return_value="正在使用 CarPlay：停车、断开后再升级"):
            reply = self.page.apply("/update", {"action": "install", "nonce": nonce, "confirmed": "1"})
        self.assertEqual(reply, {"m": "正在使用 CarPlay：停车、断开后再升级", "at": "update"})
        html = self.page.render("m=正在使用 CarPlay：停车、断开后再升级&at=update")
        self.assertIn('<p class=foot>正在使用 CarPlay：停车、断开后再升级</p>', html)
        self.assertNotIn('class="banner', html)
        update.save(self.state / "update-status.json", {"phase": "installing", "message": "正在安装", "at": time.time()})
        html = self.page.render("")
        self.assertIn("正在升级", html)
        self.assertNotIn("value=install", html)

    def test_a_network_warning_is_shown(self):
        self.status["warning"] = "局域网地址是 192.168.77.1/24"
        self.assertIn("局域网地址是 192.168.77.1/24", self.page.render(""))


if __name__ == "__main__":
    unittest.main()
