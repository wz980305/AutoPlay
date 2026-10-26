"""bt-bridge reason words (bridge_reasons.py): pure, so they run where dbus-next is not installed."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "linux/bt-bridge"))
import bridge_reasons


class BridgeReasonTests(unittest.TestCase):
    def test_bluez_errors_map_to_one_word(self):
        cases = {
            "ConnectProfile: org.bluez.Error.Failed: br-connection-key-missing": "pairing-lost",
            "org.bluez.Error.AuthenticationFailed: Authentication Failed": "pairing-lost",
            "ConnectProfile: org.bluez.Error.Failed: br-connection-page-timeout": "page-timeout",
            "ConnectProfile: org.bluez.Error.Failed: br-connection-busy": "busy",
            "br-connection-already-connected": "busy",
            "stdin closed: invitation cancelled by the receiver": "aborted",
            "RFCOMM connection timed out": "timeout",
            "D-Bus operation timed out": "timeout",
            "device is not paired on this adapter; pair using bluetoothctl first": "not-paired",
            "adapter is powered off; enable it explicitly before connecting": "powered-off",
            "device is blocked in BlueZ": "blocked",
            "no BlueZ adapter found; check the F50 driver and bluetoothd": "no-adapter",
            "BlueZ disappeared or restarted": "bluez-gone",
            "org.bluez.Error.NotAuthorized": "auth-failed",
            "something else entirely": "unknown",
        }
        for text, word in cases.items():
            self.assertEqual(bridge_reasons.failure_reason(text), word, text)
            self.assertIn(word, bridge_reasons.WORDS)
        self.assertEqual(bridge_reasons.report(TimeoutError()), "bt-bridge: reason=timeout")
        self.assertEqual(bridge_reasons.failure_reason(OSError("Connection refused")), "refused")


if __name__ == '__main__':
    unittest.main()
