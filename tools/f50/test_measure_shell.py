"""Run the measurement shell against synthetic proc files only, without a box."""
import csv
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('measure.sh')


class MeasureShellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        proc = self.root / 'proc'
        (proc / 'net').mkdir(parents=True)
        (proc / 'sys/kernel/random').mkdir(parents=True)
        (proc / 'sys/kernel/random/boot_id').write_text('testboot-0000\n')
        (proc / 'stat').write_text('cpu 10 0 5 85 0 0 0 0\ncpu0 10 0 5 85 0 0 0 0\n')
        (proc / 'interrupts').write_text(' CPU0\n')
        (proc / 'uptime').write_text('100 80\n')
        (proc / 'loadavg').write_text('0.1 0.1 0.1 1/2 3\n')
        (proc / 'meminfo').write_text('MemAvailable: 100000 kB\n')
        self.net(1000)

    def net(self, value):
        (self.root / 'proc/net/dev').write_text(f'wlan0: {value} 0 0 0 0 0 0 0 {value} 0 0 0 0 0 0 0\n')

    def run_sample(self, name='capture', *args, **env):
        out = self.root / (name + '.csv')
        result = subprocess.run(['sh', str(SCRIPT), '--once', '--out', str(out), '--persist', str(self.root / ('persist-' + name)), *args],
                                env=dict(os.environ, AUTOPLAY_SYSROOT=str(self.root), AUTOPLAY_MEASURE_CONF=str(self.root / 'absent'), **env),
                                capture_output=True, text=True, timeout=10)
        return result, out

    def test_rotation_preserves_one_header_and_does_not_duplicate_persisted_rows(self):
        result, out = self.run_sample(MAX_TMP_BYTES='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(out.read_text().splitlines()), 2)
        self.run_sample(MAX_TMP_BYTES='1')
        self.assertEqual(len(out.read_text().splitlines()), 3)
        persisted = next((self.root / 'persist-capture').glob('*.csv'))
        self.assertEqual(len(persisted.read_text().splitlines()), 3)

    def test_independent_outputs_have_independent_counter_state(self):
        self.run_sample('one')
        self.net(2000)
        _, out = self.run_sample('two')
        with out.open() as f:
            self.assertEqual(list(csv.DictReader(f))[0]['wlan0_rx_bytes_d'], '')

    def test_network_reset_does_not_report_negative_throughput(self):
        self.run_sample()
        self.net(10)
        _, out = self.run_sample()
        with out.open() as f:
            self.assertEqual(list(csv.DictReader(f))[-1]['wlan0_rx_bytes_d'], '')

    def test_invalid_interval_is_rejected_before_sampling(self):
        for value in ('0', '-1', 'bad'):
            result, out = self.run_sample('invalid', '--interval', value)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(out.exists())
