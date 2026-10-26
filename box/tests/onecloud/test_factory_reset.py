"""Factory reset: secure wipe of the box's own data (reliability_audit #24)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import factory_reset


class FactoryResetTests(unittest.TestCase):
    def test_wipes_state_shreds_secrets_and_keeps_identity_unless_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, content in (("state/receiver/pairings.properties", "pairing secret"),
                                      ("state/receiver/browser-token", "tok"), ("state/bluetooth/AA/info", "[LinkKey]"),
                                      ("state/tls/own/key.pem", "KEY"), ("state/own-domain.json", "{}"),
                                      ("state/logs/abc/receiver.log", "log"), ("state/clock-floor", "1790000000"),
                                      ("identity/offline-mfi/identity.pk8", "ID"), ("identity/offline-mfi/certificate.p7b", "CERT")):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            calls = []
            removed = factory_reset.wipe(root, identity=False, uci=lambda argv, **kw: calls.append(argv))
            self.assertFalse((root / "state/receiver").exists())
            self.assertFalse((root / "state/bluetooth").exists())
            self.assertFalse((root / "state/tls").exists())
            self.assertFalse((root / "state/logs").exists())
            self.assertTrue((root / "state/clock-floor").exists(), "the clock floor is no secret and stays")
            self.assertTrue((root / "identity/offline-mfi/identity.pk8").exists())
            self.assertIn("state/receiver", removed)
            self.assertIn(["uci", "set", "dashplay.main.duckdns_token="], calls)
            self.assertIn(["uci", "commit", "dashplay"], calls)
            factory_reset.wipe(root, identity=True, uci=lambda argv, **kw: None)
            self.assertFalse((root / "identity/offline-mfi/identity.pk8").exists())
            self.assertTrue((root / "identity/offline-mfi").is_dir(), "the empty directory stays for the next files")

    def test_shred_overwrites_before_unlinking(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "key.pem"
            path.write_bytes(b"SECRET")
            written = []
            real_open = open
            def spy(file, mode="r", *a, **k):
                handle = real_open(file, mode, *a, **k)
                if "b" in mode and "+" in mode:
                    written.append(file)
                return handle
            with patch("builtins.open", spy):
                factory_reset.shred(path)
            self.assertFalse(path.exists())
            self.assertEqual(written, [path])


if __name__ == '__main__':
    unittest.main()
