"""Offline installer gates: no device connection and no shared identity download."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('install_safety', Path(__file__).resolve().parents[2] / 'scripts/f50-install.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class InstallSafetyTests(unittest.TestCase):
    def test_b13_or_unknown_stops_before_device_access(self):
        for build in ('B13', None, '', 'B16-unverified', 'B15'):
            with self.subTest(build=build), patch.object(install, 'Fdl') as fdl:
                w = Mock()
                with self.assertRaisesRegex(install.Stop, 'B13/unknown'):
                    install.flash(w, SimpleNamespace(stock_build=build))
                fdl.assert_not_called()
                w.run.assert_not_called()

    def test_only_explicit_b16_declarations_pass_early_gate(self):
        install.require_stock_build('B16')
        install.require_stock_build(install.B16)

    def test_identity_requires_local_directory_before_remote_access(self):
        w = Mock()
        with self.assertRaisesRegex(install.Stop, 'local identity'):
            install.identity(w, SimpleNamespace(dir=None))
        w.ssh.assert_not_called()

    def test_incomplete_local_identity_is_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as d, patch.object(install.urllib.request, 'urlopen') as network:
            (Path(d) / 'identity.pk8').write_bytes(b'synthetic')
            w = Mock()
            with self.assertRaisesRegex(install.Stop, 'certificate.p7b'):
                install.identity(w, SimpleNamespace(dir=d))
            network.assert_not_called()
            w.ssh.assert_not_called()
