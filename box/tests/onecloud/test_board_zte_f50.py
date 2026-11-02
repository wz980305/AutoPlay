from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/onecloud"))
import board_zte_f50


class ResetControllerTests(unittest.TestCase):
    """rfkill power cycle of the Bluetooth function: the quick way first, the vendor's 1 s + 2 s waits only after a failed init."""
    def run_reset(self, results):
        import tempfile
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        state = Path(d.name) / "state"
        writes, sleeps, outcomes = [], [], list(results)
        real = Path.write_text
        def record(path, text):
            if path == state: writes.append(text.strip())
            return real(path, text)
        from unittest.mock import patch
        with patch.object(Path, "write_text", record):
            try:
                way = board_zte_f50.reset_controller(state, lambda: outcomes.pop(0), sleep=sleeps.append)
            except SystemExit as error:
                way = error
        return way, writes, sleeps

    def test_quick_way_when_the_init_takes(self):
        self.assertEqual(self.run_reset([True]), ("quick", ["0", "1"], [0.2]))

    def test_vendor_waits_after_a_failed_init(self):
        self.assertEqual(self.run_reset([False, True]), ("with the vendor's waits", ["0", "1", "0", "1"], [0.2, 1, 2]))

    def test_two_failures_stop_the_helper(self):
        way, writes, sleeps = self.run_reset([False, False])
        self.assertIsInstance(way, SystemExit)
        self.assertEqual(sleeps, [0.2, 1, 2])


class StopChildrenTests(unittest.TestCase):
    def test_all_children_go_within_one_deadline(self):
        # One child after the other, 8 s each, outlived the supervisor's 8 s for the helper: the helper was
        # killed and bluetoothd/btattach stayed, so the next start found hci0 and gave up (review 2026-10-12).
        stubborn = [("c%d" % i, subprocess.Popen(["sh", "-c", "trap '' TERM; sleep 30"], start_new_session=True))
                    for i in range(3)]
        time.sleep(0.2)
        started = time.monotonic()
        board_zte_f50.stop_children(stubborn, timeout=1)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertTrue(all(child.poll() is not None for _, child in stubborn))


if __name__ == "__main__":
    unittest.main()


class RfkillTests(unittest.TestCase):
    """F50/MU300: hci0 can come up soft-blocked (DashPlay 2026-10-25); unblock by type after hci0, never a fixed index."""

    def make(self, *radios):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, kind, soft, hard in radios:
            node = root / name; node.mkdir()
            (node / "type").write_text(kind + "\n"); (node / "soft").write_text(soft + "\n"); (node / "hard").write_text(hard + "\n")
        return root

    def test_unblocks_the_soft_blocked_bluetooth_nodes_and_leaves_wifi_alone(self):
        root = self.make(("rfkill0", "wlan", "1", "0"), ("rfkill1", "bluetooth", "0", "0"), ("rfkill5", "bluetooth", "1", "0"))
        self.assertEqual(board_zte_f50.unblock_rfkill(root), ["rfkill5", "rfkill1"])
        self.assertEqual((root / "rfkill5" / "soft").read_text().strip(), "0")
        self.assertEqual((root / "rfkill0" / "soft").read_text().strip(), "1", "the Wi-Fi radio is not touched")
        self.assertEqual(board_zte_f50.unblock_rfkill(root), ["rfkill1", "rfkill5"], "idempotent: nothing left to unblock")

    def test_a_hard_block_and_a_missing_node_stop_the_helper(self):
        with self.assertRaisesRegex(SystemExit, "hard-blocked"):
            board_zte_f50.unblock_rfkill(self.make(("rfkill2", "bluetooth", "1", "1")))
        with self.assertRaisesRegex(SystemExit, "not found"):
            board_zte_f50.unblock_rfkill(self.make(("rfkill0", "wlan", "0", "0")))

    def test_the_reason_words_cover_the_new_exits(self):
        import supervisor_openwrt
        self.assertEqual(supervisor_openwrt.helper_reason("Bluetooth rfkill not found after hci0\n"), "rfkill")
        self.assertEqual(supervisor_openwrt.helper_reason("Bluetooth rfkill unblock failed (soft is still 1, rfkill5)\n"), "rfkill")
        self.assertEqual(supervisor_openwrt.helper_reason("Bluetooth is hard-blocked (rfkill hard=1, rfkill5)\n"), "rfkill-hard")
