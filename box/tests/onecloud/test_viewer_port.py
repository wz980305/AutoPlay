"""The viewer port: the owner's choice in LuCI, an older install's saved port, else 17989 (18443 until 1.6.7)."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import viewer_port


class ViewerPortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, value):
        path = self.state / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def test_default(self):
        self.assertEqual(viewer_port.resolve(self.state), 17989)


    def test_saved_receiver_port_survives_an_update(self):
        # A port changed by hand before the option existed is still used when the option is absent.
        self.write("receiver/config.json", {"httpPort": 19500})
        self.assertEqual(viewer_port.resolve(self.state), 19500)


    def test_invalid_saved_port_falls_back(self):
        self.write("receiver/config.json", {"httpPort": 7000})
        self.assertEqual(viewer_port.resolve(self.state), 17989)

    def test_valid_range_and_reserved(self):
        for port in (1024, 17989, 18443, 65535):
            self.assertTrue(viewer_port.valid(port))
        for port in (80, 443, 7000, 1023, 65536, "x", None):
            self.assertFalse(viewer_port.valid(port))

    # 1.6.8: the default moves from 18443 to 17989 (the owner, 2026-11-16) -------------------------------------

    def test_a_new_box_listens_on_17989(self):
        self.assertEqual(viewer_port.choose("", self.state), (17989, True))

    def test_a_box_that_carries_the_old_default_moves_once(self):
        # The supervisor mirrors the port in use into the uci, so every installed box carries "18443".
        self.assertEqual(viewer_port.choose("18443", self.state), (17989, True))
        viewer_port.settle(self.state)
        self.assertEqual(viewer_port.choose("17989", self.state), (17989, False))
        # ... and an older install that only ever had the receiver's own file
        other = self.state / "other"
        (other / "receiver").mkdir(parents=True)
        (other / "receiver/config.json").write_text(json.dumps({"httpPort": 18443}))
        self.assertEqual(viewer_port.choose("", other), (17989, True))

    def test_18443_chosen_after_the_move_is_the_owners_and_stays(self):
        viewer_port.settle(self.state)
        self.assertEqual(viewer_port.choose("18443", self.state), (18443, False))

    def test_another_port_of_the_owners_is_never_touched(self):
        self.assertEqual(viewer_port.choose("19500", self.state), (19500, True))
        self.write("receiver/config.json", {"httpPort": 19500})
        self.assertEqual(viewer_port.choose("", self.state), (19500, True))

    def test_the_start_an_update_is_checking_keeps_the_port(self):
        # A version that fails the check is replaced by the one before, which reads the same uci and has no
        # redirect from 18443: the car's bookmark would lead nowhere. The move waits for the next start.
        self.assertEqual(viewer_port.choose("18443", self.state, hold=True), (18443, False))
        self.assertFalse((self.state / viewer_port.MOVED).exists())
        self.assertEqual(viewer_port.choose("18443", self.state), (17989, True))

    def test_a_state_that_cannot_be_written_is_not_fatal(self):
        viewer_port.settle(self.state / "missing")   # no such directory: asked again at the next start


if __name__ == "__main__":
    unittest.main()
