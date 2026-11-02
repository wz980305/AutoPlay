"""The autoplay package's uci-defaults (files/90-autoplay-tesla) against a fake `uci`: the LAN moves to 100.96.0.1,
the 5 GHz radio moves to CN / 149-165, and a channel the owner already chose in 149-165 is kept (1.0.1).

Run: python3 -m unittest discover -s openwrt/tests
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "autoplay" / "files" / "90-autoplay-tesla"
FAKE_UCI = """#!/bin/sh
# key=value lines in $UCI_STATE; commits appended to $UCI_STATE.commits
DB=$UCI_STATE; [ "$1" = -q ] && shift
case $1 in
  get) grep "^$2=" "$DB" | head -1 | cut -d= -f2- ;;
  set) key=${2%%=*}; val=${2#*=}; grep -v "^$key=" "$DB" > "$DB.n"; echo "$key=$val" >> "$DB.n"; mv "$DB.n" "$DB" ;;
  delete) grep -v "^$2=" "$DB" > "$DB.n"; mv "$DB.n" "$DB" ;;
  show) grep "^$2\\." "$DB" | sed "s/=\\(.*\\)$/='\\1'/" ;;
  commit) echo "$2" >> "$DB.commits" ;;
esac
"""
LAN = ["network.lan.proto=static", "network.lan.ipaddr=100.96.0.1", "network.lan.netmask=255.255.255.0"]


@unittest.skipUnless(SCRIPT.exists(), "openwrt tree not present")
class UciDefaultsTests(unittest.TestCase):
    def run_script(self, *lines):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "bin"; binary.mkdir()
            (binary / "uci").write_text(FAKE_UCI); (binary / "uci").chmod(0o755)
            db = Path(tmp) / "db"; db.write_text("".join(line + "\n" for line in lines))
            commits = Path(tmp) / "db.commits"; commits.write_text("")
            env = dict(os.environ, UCI_STATE=str(db), PATH=f"{binary}:{os.environ.get('PATH', '')}")
            # `wifi reload` and `/etc/init.d/dnsmasq reload` are backgrounded by the script and fail harmlessly here.
            subprocess.run(["sh", str(SCRIPT)], env=env, check=True, capture_output=True, timeout=30)
            state = dict(line.split("=", 1) for line in db.read_text().splitlines() if "=" in line)
            return state, commits.read_text().split()

    def test_a_vendor_tr_radio_locked_to_36_48_moves_to_cn_149(self):
        state, commits = self.run_script(*LAN, "wireless.radio0.band=5g", "wireless.radio0.country=TR",
                                         "wireless.radio0.channel=36", "wireless.radio0.channels=36 40 44 48")
        self.assertEqual(state["wireless.radio0.country"], "CN")
        self.assertEqual(state["wireless.radio0.channel"], "149")
        self.assertNotIn("wireless.radio0.channels", state, "the 36-48 lock goes")
        self.assertIn("wireless", commits)

    def test_an_owner_channel_in_149_165_survives_an_upgrade(self):
        for channel in ("153", "157", "161", "165"):
            with self.subTest(channel=channel):
                state, commits = self.run_script(*LAN, "wireless.radio0.band=5g", "wireless.radio0.country=CN",
                                                 f"wireless.radio0.channel={channel}")
                self.assertEqual(state["wireless.radio0.channel"], channel)
                self.assertNotIn("wireless", commits, "nothing to commit: the radio is already right")

    def test_a_channel_outside_149_165_moves_even_under_cn(self):
        state, _ = self.run_script(*LAN, "wireless.radio0.band=5g", "wireless.radio0.country=CN", "wireless.radio0.channel=44")
        self.assertEqual(state["wireless.radio0.channel"], "149")

    def test_the_2g_radio_is_left_alone_and_the_lan_moves(self):
        state, commits = self.run_script("network.lan.proto=static", "network.lan.ipaddr=192.168.77.1",
                                         "network.lan.netmask=255.255.255.0", "wireless.radio1.band=2g",
                                         "wireless.radio1.country=TR", "wireless.radio1.channel=6")
        self.assertEqual(state["network.lan.ipaddr"], "100.96.0.1")
        self.assertEqual(state["wireless.radio1.channel"], "6")
        self.assertEqual(state["wireless.radio1.country"], "TR")
        self.assertIn("network", commits)
        self.assertNotIn("wireless", commits)


if __name__ == "__main__":
    unittest.main()
