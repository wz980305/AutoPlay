import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import diagnostics
import platform_openwrt

STATIONS = """Station 02:00:00:00:00:a1 (on wlx020000000010)
\tinactive time:\t40 ms
\ttx packets:\t12000
\ttx retries:\t3500
\ttx failed:\t12
\tsignal:  \t-61 [-61] dBm
\ttx bitrate:\t292.5 MBit/s
\trx bitrate:\t433.3 MBit/s
Station 02:00:00:00:00:a4 (on wlx020000000010)
\tinactive time:\t0 ms
\tsignal:  \t-40 dBm
"""


class ParseTests(unittest.TestCase):
    def test_stations(self):
        peers = platform_openwrt.parse_stations(STATIONS)
        self.assertEqual(peers[0], {'peer': '00:a1', 'signal': -61, 'rx_mbps': 433.3, 'tx_mbps': 292.5,
                                    'tx_packets': 12000, 'tx_retries': 3500, 'tx_failed': 12, 'inactive_ms': 40})
        self.assertEqual(peers[1]['peer'], '00:a4')
        self.assertIsNone(peers[1]['tx_retries'])

    def test_the_drive_log_keeps_what_the_driver_said_and_who_the_station_is(self):
        # The F50's firmware reports the address alone: eight nulls a station, five stations, every 10 s.
        known = {'02:00:00:00:00:a4': {'ip': '100.96.0.150', 'name': 'iPhone'}}
        peers = platform_openwrt.stations(STATIONS, known)
        self.assertEqual(peers[1], {'peer': '00:a4', 'signal': -40, 'inactive_ms': 0, 'ip': '100.96.0.150', 'name': 'iPhone'})
        self.assertEqual(platform_openwrt.stations('Station 02:00:00:00:00:B7 (on wlan0)\n', {}), [{'peer': '00:B7'}])

    def test_neighbours_come_from_the_arp_table_and_the_leases(self):
        with tempfile.TemporaryDirectory() as tmp:
            arp, leases = Path(tmp) / 'arp', Path(tmp) / 'leases'
            arp.write_text('IP address       HW type     Flags       HW address            Mask     Device\n'
                           '100.96.0.150     0x1         0x2         02:00:00:00:00:A4     *        br-lan\n'
                           '100.96.0.9       0x1         0x0         00:00:00:00:00:00     *        br-lan\n')
            leases.write_text('1790000000 02:00:00:00:00:a4 100.96.0.150 iPhone 01:02\n'
                              '1790000000 02:00:00:00:00:c1 100.96.0.160 * *\n')
            self.assertEqual(platform_openwrt.neighbours(arp, leases),
                             {'02:00:00:00:00:a4': {'ip': '100.96.0.150', 'name': 'iPhone'},
                              '02:00:00:00:00:c1': {'ip': '100.96.0.160'}})
            self.assertEqual(platform_openwrt.neighbours(Path(tmp) / 'no', Path(tmp) / 'no'), {})


class DiagLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / 'diag'

    def test_append_rotates_and_reads_both_files(self):
        log = diagnostics.DiagLog(self.dir, max_bytes=60)
        for n in range(6):
            log.append({'n': n, 'pad': 'x' * 20})
        self.assertTrue((self.dir / 'diag.1.jsonl').exists())
        numbers = [json.loads(line)['n'] for line in log.text().splitlines()]
        self.assertEqual(numbers, sorted(numbers))
        self.assertEqual(numbers[-1], 5)
        self.assertEqual((self.dir / 'diag.jsonl').stat().st_mode & 0o777, 0o600)

    def test_tail_follows_a_rewritten_log_and_keeps_partial_lines(self):
        path = Path(self.tmp.name) / 'receiver.log'
        tail = diagnostics.LogTail(path)
        self.assertEqual(tail.read(), [])
        path.write_text('a\nb\npart')
        self.assertEqual(tail.read(), ['a', 'b'])
        with path.open('a') as out:
            out.write('ial\nc\n')
        self.assertEqual(tail.read(), ['partial', 'c'])
        path.unlink(); path.write_text('new\n')   # the receiver restarted and rewrote its log
        self.assertEqual(tail.read(), ['new'])

    def test_keep_filters_and_caps(self):
        lines = ['noise'] * 5 + [f'123 [viewer] INFO viewer - viewer stats client=1 fps={n}' for n in range(50)]
        kept = diagnostics.keep(lines)
        self.assertEqual(len(kept), diagnostics.MAX_LINES)
        self.assertTrue(kept[-1].endswith('fps=49'))
        self.assertEqual(diagnostics.keep(['boot 31.2s invitation sent', 'DEBUG x']), ['boot 31.2s invitation sent'])

    def test_the_pages_report_is_kept_whole_and_the_boxs_own_decisions_are_kept(self):
        # 2026-11-10: every viewer line ended at "height", before its stalls, lag and revived numbers.
        report = '170382138 [x] INFO viewer - viewer stats client=1 ' + ' '.join(f'k{n}=1' for n in range(150)) + ' revived=2'
        self.assertGreater(len(report), 300)
        self.assertTrue(diagnostics.keep([report])[0].endswith('revived=2'))
        self.assertEqual(len(diagnostics.keep(['1 [x] WARN y - ' + 'z' * 900])[0]), 300)
        for line in ('1 [carplay-supervisor] INFO playport - no viewer for 300 s: CarPlay released until a page opens',
                     '1 [carplay-supervisor] INFO playport - a viewer opened the page: inviting the iPhone again',
                     '1 [carplay-supervisor] INFO playport - wireless session dropped; inviting its iPhone once without waiting',
                     '1 [x] INFO playport - car location switched on datum=auto',
                     '1 [x] INFO playport - car location: last 60 s new=58 repeated=2 datum=auto(gcj02)'):
            self.assertEqual(diagnostics.keep([line]), [line])

    def test_what_the_iphone_says_about_sound_is_kept(self):
        # 2026-11-15: the owner asked about silence after the Tesla's own Apple Music; the drive record held no line
        # about sound at all, as the receiver's two were not kept (docs/AUDIO.md §六).
        for line in ('1 [airplay-control] INFO playport - CarPlay resource ownership: [resourceID=1,entity=1, resourceID=2,entity=1]',
                     '1 [airplay-control] INFO playport - audio duckAudio level=0.200 ms=500 volume=-14.0 count=3',
                     '1 [airplay-control] INFO playport - audio unduckAudio level=1.000 ms=500 volume=- count=3'):
            self.assertEqual(diagnostics.keep([line]), [line])
        self.assertEqual(diagnostics.keep(['1 [x] DEBUG playport - AirPlay command type=modesChanged params=resources']), [])

    def test_a_download_opens_with_the_release_and_the_clock(self):
        log = diagnostics.DiagLog(Path(self.tmp.name) / 'd')
        log.append({'uptime': 5})
        lines = log.text({'event': 'download', 'version': '1.4.3', 'wall': 1}).splitlines()
        self.assertEqual(json.loads(lines[0]), {'event': 'download', 'version': '1.4.3', 'wall': 1})
        self.assertEqual(json.loads(lines[1]), {'uptime': 5})
        self.assertEqual(log.text(), '{"uptime":5}\n')

    def test_what_the_car_can_reach_is_said_when_it_changes(self):
        class Platform:
            def boot_id(self): return 'abcdef0123'
            def diagnostics(self): return {}
        status = {'mode': 'openwrt', 'tesla_internet': 'online'}
        stopped, log = threading.Event(), diagnostics.DiagLog(self.dir)
        program = Path(self.tmp.name) / 'p'; program.mkdir()
        diagnostics.start(stopped, log, Path(self.tmp.name) / 'none.log', Platform(), status, interval=0.03, program=program)
        for _ in range(200):
            if len(log.text().splitlines()) >= 4:
                break
            stopped.wait(0.02)
        status['tesla_internet'] = 'offline'
        seen = len(log.text().splitlines())
        for _ in range(200):
            if len(log.text().splitlines()) >= seen + 3:
                break
            stopped.wait(0.02)
        stopped.set()
        said = [r['tesla_internet'] for r in map(json.loads, log.text().splitlines()) if 'tesla_internet' in r]
        self.assertEqual(said, ['online', 'offline'])

    def test_loop_writes_records_with_platform_and_log(self):
        class Platform:
            def boot_id(self): return 'abcdef0123'
            def diagnostics(self): return {'usb_resets': 0, 'link': {'signal': -60}}
        receiver = Path(self.tmp.name) / 'receiver.log'
        receiver.write_text('x WARN something\n')
        stopped = threading.Event()
        log = diagnostics.DiagLog(self.dir)
        program = Path(self.tmp.name) / 'program'; program.mkdir()
        (program / 'version.txt').write_text('2026.10.20\n')
        diagnostics.start(stopped, log, receiver, Platform(), {'mode': 'sta'}, interval=0.05, program=program)
        for _ in range(100):
            if len(log.text().splitlines()) >= 2:
                break
            stopped.wait(0.02)
        stopped.set()
        records = [json.loads(line) for line in log.text().splitlines()]
        self.assertEqual(records[0]['event'], 'start')
        self.assertEqual(records[0]['boot'], 'abcdef01')
        self.assertEqual(records[0]['version'], '2026.10.20', 'which release the box runs opens every start')
        self.assertEqual(records[1]['mode'], 'sta')
        self.assertEqual(records[1]['link'], {'signal': -60})
        self.assertEqual(records[1]['log'], ['x WARN something'])




class LogMirrorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root, self.run = Path(tmp.name) / 'logs', Path(tmp.name) / 'run'
        self.root.mkdir()
        self.run.mkdir()

    def test_full_logs_survive_restarts_and_truncation(self):
        receiver = self.run / 'receiver.log'
        receiver.write_text('one\ntwo\npartial')
        mirror = diagnostics.LogMirror(self.root, self.run, 'abcdef0123456789')
        mirror.directory.mkdir()
        offsets, handles = {}, {}
        mirror.cycle(offsets, handles)
        self.assertEqual((mirror.directory / 'receiver.log').read_text(), 'one\ntwo\n')   # partial line waits
        # A supervisor restart in the same boot resumes from the saved offsets: nothing twice.
        with receiver.open('a') as log:
            log.write('\nthree\n')
        again = diagnostics.LogMirror(self.root, self.run, 'abcdef0123456789')
        again.cycle({k: tuple(v) for k, v in again.load().items()}, {})
        self.assertEqual((mirror.directory / 'receiver.log').read_text(), 'one\ntwo\npartial\nthree\n')
        # Each receiver start rewrites its log: start over and say so.
        receiver.unlink()
        receiver.write_text('fresh\n')
        offsets = {k: tuple(v) for k, v in again.load().items()}
        again.cycle(offsets, {})
        self.assertTrue((mirror.directory / 'receiver.log').read_text().endswith('restarted]\nfresh\n'))

    def started(self):
        """A mirror as the supervisor runs it, its minute far away: only what the test asks for is copied."""
        mirror = diagnostics.LogMirror(self.root, self.run, 'abcdef0123456789')
        stopped = threading.Event()
        mirror.start(stopped, interval=3600)
        self.addCleanup(lambda: (stopped.set(), mirror.wake.set(), mirror.thread.join(5)))   # its last cycle, then the directory goes
        for _ in range(100):   # its first cycle
            if mirror.state_file.exists():
                break
            time.sleep(0.02)
        return mirror

    def cycle(self, mirror):
        with mirror.lock:
            mirror.cycle(mirror.offsets, mirror.handles)

    def test_a_restarted_child_keeps_what_the_one_before_it_wrote_last(self):
        # Review 2026-11-22: platform.start() emptied RUN/<name>.log up to a minute after its last copy, so the kept
        # logs of a crashed receiver ended before the reason; and a new log longer than the old one was not seen as
        # new, its beginning skipped. renew() (platform.before_start) copies first and starts the log again.
        receiver = self.run / 'receiver.log'
        receiver.write_text('started\nsession active\n')
        mirror = self.started()
        kept = mirror.directory / 'receiver.log'
        self.assertEqual(kept.read_text(), 'started\nsession active\n')
        with receiver.open('a') as log:
            log.write('Exception in thread main: why it ended\nand a last line cut off')
        mirror.renew('receiver')
        self.assertEqual(receiver.read_text(), '', 'the log begins again')
        with receiver.open('w') as log:   # platform.start()
            log.write('started again, and this run has written more than the one before it\nsecond line\n')
        self.cycle(mirror)
        self.assertEqual(kept.read_text(), 'started\nsession active\nException in thread main: why it ended\n'
                         'and a last line cut off\n[log mirror: receiver.log restarted]\n'
                         'started again, and this run has written more than the one before it\nsecond line\n')
        self.assertEqual(json.loads(mirror.state_file.read_text())['receiver.log'][1], receiver.stat().st_size)

    def test_a_first_start_costs_nothing_and_a_broken_card_never_stops_a_child(self):
        mirror = self.started()
        with patch.object(mirror, 'cycle') as cycle:
            mirror.renew('bluetooth')            # no log yet: a child's first start after a boot
            (self.run / 'bluetooth.log').write_text('')
            mirror.renew('bluetooth')            # an empty one
            cycle.assert_not_called()
        self.assertFalse((mirror.directory / 'bluetooth.log').exists())
        (self.run / 'bluetooth.log').write_text('line\n')
        with patch.object(mirror, 'cycle', side_effect=OSError('card gone')), patch('builtins.print') as said:
            mirror.renew('bluetooth')            # must return, whatever the card does
        self.assertIn('not copied before its restart', said.call_args.args[0])
        # Before start() nothing has been copied and nothing is touched.
        idle = diagnostics.LogMirror(self.root, self.run, 'fedcba9876543210')
        idle.renew('bluetooth')
        self.assertEqual((self.run / 'bluetooth.log').read_text(), 'line\n')
        self.assertFalse(idle.directory.exists())

    def test_offsets_are_replaced_whole(self):
        # A power cut while .offsets.json was written in place left a cut-off file, read as no offsets: the next
        # start copied every log of the boot a second time.
        (self.run / 'receiver.log').write_text('one\n')
        mirror = diagnostics.LogMirror(self.root, self.run, 'abcdef0123456789')
        mirror.directory.mkdir()
        replaced = []
        real = Path.replace
        with patch.object(Path, 'replace', autospec=True, side_effect=lambda a, b: (replaced.append((a.name, Path(b).name)), real(a, b))[1]):
            mirror.cycle({}, {})
        self.assertEqual(replaced, [('.offsets.json.tmp', '.offsets.json')])
        self.assertEqual(sorted(p.name for p in mirror.directory.iterdir()), ['.offsets.json', 'receiver.log'])

    @patch('diagnostics.subprocess.run')
    def test_only_run_logs_are_kept(self, run):
        (self.run / 'supervisor.log').write_text('boot 12.0s supervisor start\n')
        mirror = diagnostics.LogMirror(self.root, self.run, 'abcdef0123456789')
        mirror.directory.mkdir()
        mirror.cycle({}, {})
        run.assert_not_called()   # OpenWrt has no journalctl; nothing is run
        self.assertEqual((mirror.directory / 'supervisor.log').read_text(), 'boot 12.0s supervisor start\n')
        self.assertEqual(sorted(p.name for p in mirror.directory.iterdir()), ['.offsets.json', 'supervisor.log'])

    def test_mirror_is_bounded_minute_wise_and_flushes_on_errors(self):
        # reliability_audit #11: 5 MB per file and boot, a cycle a minute, at once when an error line arrives.
        self.assertEqual(diagnostics.MIRROR_INTERVAL, 60)
        self.assertEqual(diagnostics.LOG_FILE_MAX, 5_000_000)
        (self.run / 'receiver.log').write_text('INFO fine\n')
        mirror = diagnostics.LogMirror(self.root, self.run, 'abcdef0123456789')
        mirror.directory.mkdir()
        offsets, handles = {}, {}
        self.assertFalse(mirror.cycle(offsets, handles))
        with (self.run / 'receiver.log').open('a') as log:
            log.write('ERROR something broke\n')
        self.assertTrue(mirror.cycle(offsets, handles), 'an error line asks for an immediate flush')
        self.assertFalse(mirror.wake.is_set())
        mirror.flush_now()
        self.assertTrue(mirror.wake.is_set())
        with patch.object(diagnostics, 'LOG_FILE_MAX', 20):
            (self.run / 'big.log').write_text('x' * 100 + '\n')
            mirror.cycle(offsets, handles)
            text = (mirror.directory / 'big.log').read_text()
            self.assertIn('size limit reached', text)
            self.assertLess(len(text), 100)

    def test_old_boots_are_pruned(self):
        for index in range(12):
            (self.root / f'boot{index:02d}').mkdir()
            os.utime(self.root / f'boot{index:02d}', (index, index))
        mirror = diagnostics.LogMirror(self.root, self.run, 'current0')
        mirror.directory.mkdir()
        mirror.prune()
        left = sorted(d.name for d in self.root.iterdir())
        self.assertEqual(len(left), diagnostics.LOG_BOOTS)
        self.assertIn('current0', left)
        self.assertNotIn('boot00', left)

    def test_network_counters_parse_snmp(self):
        with patch('diagnostics.Path.read_text', return_value=(
                'Tcp: RtoAlgorithm OutSegs RetransSegs\nTcp: 1 500 7\n'
                'Udp: InDatagrams RcvbufErrors\nUdp: 900 3\n')):
            self.assertEqual(diagnostics.net_counters(),
                             {'tcp_out': 500, 'tcp_retrans': 7, 'udp_in': 900, 'udp_rcvbuf_err': 3})



class LagTests(unittest.TestCase):
    @patch('diagnostics.subprocess.run')
    def test_ping_burst_and_tcp_state(self, run):
        run.return_value = Mock(stdout='5 packets transmitted, 4 received, 20% packet loss, time 410ms\n'
                                       'rtt min/avg/max/mdev = 2.1/48.5/180.0/60.2 ms\n')
        self.assertEqual(diagnostics.ping_stats('10.0.0.5'), {'loss': 20.0, 'min': 2.1, 'avg': 48.5, 'max': 180.0})
        run.return_value = Mock(stdout='ESTAB 0 0 10.0.0.2:7000 10.0.0.5:51000\n'
                                       '\t cubic rtt:85.2/20.1 ato:40 bytes_received:123456 retrans:0/7 rcv_rtt:120.5 lost:2\n')
        self.assertEqual(diagnostics.tcp_stats('10.0.0.5'),
                         [{'local': '7000', 'rtt': 85.2, 'rcv_rtt': 120.5, 'retrans': 7.0, 'rx_bytes': 123456.0, 'lost': 2.0}])
        run.return_value = Mock(stdout='5 packets transmitted, 0 received, 100% packet loss, time 4100ms\n')
        self.assertEqual(diagnostics.ping_stats('10.0.0.5'), {'loss': 100.0})

    def test_a_ping_without_the_short_interval_is_asked_the_plain_way_and_says_why_it_failed(self):
        # 2026-11-10: "phone": null and "tcp": null in all 941 records of a drive.
        calls = []
        def run(argv, **_):
            calls.append(argv)
            if '-i' in argv:
                return Mock(stdout='', stderr='ping: invalid number \'0.1\'\n')
            return Mock(stdout='3 packets transmitted, 3 packets received, 0% packet loss\n'
                               'round-trip min/avg/max = 1.2/3.4/9.9 ms\n', stderr='')
        with patch.object(diagnostics, '_ping_interval', True), patch('diagnostics.subprocess.run', side_effect=run):
            self.assertEqual(diagnostics.ping_stats('10.0.0.5'), {'loss': 0.0, 'min': 1.2, 'avg': 3.4, 'max': 9.9})
            self.assertEqual(diagnostics.ping_stats('10.0.0.5')['avg'], 3.4)
            self.assertEqual(sum('-i' in argv for argv in calls), 1, 'remembered')
        with patch.object(diagnostics, '_ping_interval', False), \
                patch('diagnostics.subprocess.run', return_value=Mock(stdout='', stderr='ping: bad address\nmore')):
            self.assertEqual(diagnostics.ping_stats('10.0.0.5'), {'error': 'ping: bad address'})
        with patch('diagnostics.subprocess.run', side_effect=FileNotFoundError):
            self.assertEqual(diagnostics.tcp_stats('10.0.0.5'), 'no ss')

    @patch('diagnostics.subprocess.run')
    def test_phone_address_on_the_current_network(self, run):
        import ipaddress
        run.return_value = Mock(stdout='default via 192.168.43.1 dev wlx proto dhcp\n')
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'receiver').mkdir()
            (state / 'receiver/phone-presence.json').write_text(json.dumps({'phones': {'02:00:00:00:00:E2': {'networks': {
                '192.168.78.0/24': {'ip': '192.168.78.63'}, '192.168.43.0/24': {'ip': '192.168.43.123'}}}}}))
            targets = diagnostics.ping_targets(state, [ipaddress.ip_network('192.168.43.0/24')])
        self.assertEqual(targets, {'gateway': '192.168.43.1', 'phone': '192.168.43.123'})


if __name__ == '__main__':
    unittest.main()
