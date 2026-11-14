"""OpenWrtPlatform stands alone: child processes, Bluetooth power, and the state helpers it relies on."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import platform_openwrt as ow
import state
import tesla_checks


class StandaloneTests(unittest.TestCase):
    def test_no_debian_import(self):
        import platform_api
        for module in (ow, platform_api):
            code = [line for line in Path(module.__file__).read_text().splitlines()
                    if line.startswith(('import ', 'from ')) or '    from ' in line]
            self.assertFalse([line for line in code if 'platform_debian' in line], module.__name__)

    def test_get_platform_is_openwrt(self):
        import platform_api
        self.assertIsInstance(platform_api.get_platform(), ow.OpenWrtPlatform)

    def test_boot_id_reads_the_kernel(self):
        with patch.object(ow.Path, 'read_text', return_value='test-boot-id\n') as read:
            self.assertEqual(ow.OpenWrtPlatform.boot_id(), 'test-boot-id')
            read.assert_called_once_with()


class ChildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.platform = ow.OpenWrtPlatform(run=Path(self.tmp.name))

    def test_start_logs_to_run_and_stop_child_terminates_only_that_child(self):
        a = self.platform.start('receiver', [sys.executable, '-c', 'import time; print("hi", flush=True); time.sleep(30)'])
        b = self.platform.start('bluetooth', [sys.executable, '-c', 'import time; time.sleep(30)'])
        for _ in range(50):
            if (Path(self.tmp.name) / 'receiver.log').read_text():
                break
            time.sleep(0.1)
        self.assertEqual([name for name, _ in self.platform.children], ['receiver', 'bluetooth'])
        self.assertIs(self.platform.child('receiver'), a)
        self.platform.stop_child('receiver')
        self.assertIsNotNone(a.poll())
        self.assertIsNone(b.poll())
        self.assertEqual([name for name, _ in self.platform.children], ['bluetooth'])
        self.assertIn('hi', (Path(self.tmp.name) / 'receiver.log').read_text())
        self.platform.stop_all()
        self.assertIsNotNone(b.poll())
        self.assertEqual(self.platform.children, [])

    def test_forget_child_drops_an_exited_child(self):
        child = self.platform.start('x', [sys.executable, '-c', 'pass'])
        child.wait(5)
        self.platform.forget_child('x')
        self.assertEqual(self.platform.children, [])

    def test_stop_child_kills_a_child_that_ignores_sigterm(self):
        self.platform.start('stubborn', [sys.executable, '-c',
                                         'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'])
        time.sleep(0.3)
        self.platform.stop_child('stubborn', timeout=0.5)
        self.assertEqual(self.platform.children, [])


class BluetoothTests(unittest.TestCase):
    """Since 1.6.3 the adapter is powered and named over D-Bus (power_adapter); bluetoothctl crashed after mu300-linux
    25.12.6 and left the box at adapter-not-powered. The D-Bus side itself is tested against a mock BlueZ on a private
    bus in tests/bluetooth/test_power.py (needs dbus-daemon and dbus-next)."""

    def test_power_waits_for_the_board_helpers_bus(self):
        with patch.dict(os.environ, {'DBUS_SYSTEM_BUS_ADDRESS': 'unix:path=/nonexistent/bus'}), \
                patch.object(ow, 'power_adapter') as power:
            self.assertFalse(ow.OpenWrtPlatform().power_bluetooth())
            power.assert_not_called()

    def test_power_on_is_d_bus_not_bluetoothctl(self):
        async def powered(name):
            self.assertEqual(name, ow.BLUETOOTH_NAME)
            return True
        with patch.dict(os.environ, {'DBUS_SYSTEM_BUS_ADDRESS': ''}), patch.object(ow, 'power_adapter', side_effect=powered), \
                patch.object(ow.subprocess, 'run') as run:
            self.assertTrue(ow.OpenWrtPlatform().power_bluetooth())
            run.assert_not_called()
        source = Path(ow.__file__).read_text()
        self.assertNotIn('["bluetoothctl"', source, "no bluetoothctl in the power path (it crashed on 25.12.6)")
        self.assertEqual(ow.BLUETOOTH_DEPS, Path(ow.__file__).resolve().parent / 'linux-bt-bridge/deps')

    def test_power_on_failure_is_false_not_an_exception(self):
        async def refused(name):
            return False

        async def broken(name):
            raise ConnectionRefusedError('no bus yet')
        for attempt in (refused, broken):
            with self.subTest(attempt=attempt.__name__), patch.dict(os.environ, {'DBUS_SYSTEM_BUS_ADDRESS': ''}), \
                    patch.object(ow, 'power_adapter', side_effect=attempt):
                self.assertFalse(ow.OpenWrtPlatform().power_bluetooth())


class StateTests(unittest.TestCase):
    def test_save_json_replaces_atomically_and_syncs_only_when_asked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'x.json'
            with patch.object(state.os, 'sync', create=True) as sync, patch.object(state.os, 'fsync') as fsync:
                state.save_json(path, {'a': 1}, sync=False)
                self.assertEqual(sync.call_count, 0)
                self.assertEqual(fsync.call_count, 0)
                state.save_json(path, {'a': 2})
                self.assertEqual(sync.call_count, 0, 'never flush unrelated filesystems')
                self.assertEqual(fsync.call_count, 2, 'persist file contents and its parent directory')
            self.assertEqual(json.loads(path.read_text()), {'a': 2})
            self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')
            self.assertFalse(path.with_suffix('.tmp').exists())
            self.assertEqual(state.load_json(path), {'a': 2})
            self.assertEqual(state.load_json(path.with_name('missing.json'), {}), {})

    def test_serialization_failure_keeps_the_previous_file_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'x.json'
            state.save_json(path, {'a': 1}, sync=False)
            with self.assertRaises(TypeError):
                state.save_json(path, {'bad': object()})
            self.assertEqual(state.load_json(path), {'a': 1})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_shared_lan_and_tesla_reach(self):
        self.assertEqual(str(state.SHARED_LAN), '100.96.0.1/24')
        self.assertTrue(state.tesla_reaches('100.96.0.1'))
        self.assertFalse(state.tesla_reaches('192.168.1.1'))
        self.assertFalse(state.tesla_reaches('not an address'))


class TeslaCheckTests(unittest.TestCase):
    def test_all_seven_names_are_answered(self):
        self.assertEqual(len(tesla_checks.TESLA_CHECK_NAMES), 7)
        for name in tesla_checks.TESLA_CHECK_NAMES:
            self.assertIsNotNone(tesla_checks.check_response(name + ':80'), name)
        self.assertIsNone(tesla_checks.check_response('example.com'))

    def test_connman_and_gstatic_replies(self):
        status, body, headers = tesla_checks.check_response('connman.vn.tesla.services')
        self.assertEqual((status, headers['X-ConnMan-Status']), (200, 'online'))
        self.assertEqual(body, tesla_checks.CONNMAN_BODY)
        self.assertEqual(tesla_checks.check_response('connectivitycheck.gstatic.com', '/generate_204?x=1')[0], 204)
        self.assertEqual(tesla_checks.check_response('connectivitycheck.gstatic.com', '/')[0], 200)
        self.assertEqual(tesla_checks.check_name('WWW.BAIDU.COM.:80'), 'www.baidu.com')


if __name__ == '__main__':
    unittest.main()
