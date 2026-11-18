import ipaddress
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import tesla_openwrt as tesla

SECTIONS = {'dns': {'.type': 'dnsmasq', 'server': ['192.0.2.53'], 'address': ['/old.example/192.0.2.1']},
            'lan': {'.type': 'dhcp', 'interface': 'lan', 'dhcp_option': ['3,192.0.2.1', '42,192.0.2.5']}}
NETWORK = {'network': 'lan', 'device': 'br-lan', 'address': ipaddress.ip_interface('100.96.0.1/24'), 'mode': 'ap'}
NAME, PORT = 'example.duckdns.org', 18080


class OpenWrtOfflineTests(unittest.TestCase):
    def test_dns_and_dhcp_plan(self):
        alias, fields = tesla.offline_fields(SECTIONS, 'lan', '100.96.0.1/24', NAME)
        self.assertEqual(alias, '100.96.0.2')
        # The box is the router: Teslas left a network without a default route ~30 s after joining (2026-10-16).
        self.assertEqual(fields['lan.dhcp_option'], ['42,192.0.2.5', '3,100.96.0.1', '6,100.96.0.1'])
        # Only the check names are local; the real upstream settings must stay untouched (2026-10-25).
        for key in ('dns.server', 'dns.noresolv', 'dns.nohosts', 'dns.resolvfile'):
            self.assertNotIn(key, fields)
        self.assertEqual(fields['dns.logqueries'], '1')
        self.assertIsNone(fields['dns.logfacility'])
        self.assertIn('/connman.vn.cloud.tesla.cn/100.96.0.2', fields['dns.address'])
        self.assertIn('/example.duckdns.org/100.96.0.1', fields['dns.address'])
        with self.assertRaises(ValueError):
            tesla.offline_fields(dict(SECTIONS, second={'.type':'dnsmasq'}), 'lan', '100.96.0.1/24', '')
        rules = tesla.redirect_rules('br-lan', alias, 18080)
        self.assertIn('ip daddr 100.96.0.2 tcp dport 80 redirect to :18080', rules)
        self.assertIn('iifname "br-lan"', rules)
        self.assertNotIn('uhttpd', rules)
        self.assertNotIn('443', rules, 'the checks never depend on the page rules')

    def test_page_rules(self):
        # 1.6.8 (the owner, 2026-11-16): https://<name>/ - a browser shows no port only for 443 - led to the viewer
        # on the box's own address, from the LAN only. The viewer's port is not changed (the owner, 2026-11-18).
        rules = tesla.page_rules('br-lan', '100.96.0.1', 18443)
        self.assertEqual(rules, f'add rule ip {tesla.TABLE} inbound iifname "br-lan" ip daddr 100.96.0.1 '
                                'tcp dport 443 redirect to :18443\n')
        self.assertIn('redirect to :19500', tesla.page_rules('br-lan', '100.96.0.1', 19500), "an owner's own port")
        # the alias of the checks (port 80 there is the settings page) is not touched
        self.assertNotIn('100.96.0.2', rules)
        for bad in (('br-lan; flush ruleset', '100.96.0.1', 18443), ('br-lan', 'name.example', 18443),
                    ('br-lan', '100.96.0.1', 443), ('br-lan', '100.96.0.1', 80), ('br-lan', '100.96.0.1', '18443 ; x')):
            with self.assertRaises(ValueError, msg=bad):
                tesla.page_rules(*bad)

    def calls(self, run, program):
        return [c for c in run.call_args_list if c.args[0][0] == program]

    def test_the_page_is_led_to_after_the_checks_and_never_in_their_way(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Mock(return_value=Mock(stdout=json.dumps({'values': SECTIONS}), returncode=0))
            controller = tesla.OfflineChecks(directory, run)
            status = {}
            controller.start(NETWORK, NAME, PORT, status, 18443)
            self.assertTrue(controller.active)
            self.assertTrue(controller.bare)
            self.assertIsNone(controller.page_note)
            loaded = [c.kwargs['input'] for c in self.calls(run, 'nft') if c.args[0][1:] == ['-f', '-']]
            self.assertEqual(len(loaded), 2, 'the checks in one load, the page in another')
            self.assertIn('tcp dport 80 redirect to :18080', loaded[0])
            self.assertNotIn('18443', loaded[0])
            self.assertEqual(loaded[1], tesla.page_rules('br-lan', '100.96.0.1', 18443))
            controller.restore()
            self.assertFalse(controller.bare, 'the table is gone with the service')

            # nft refuses the page rule: the checks stay, the address keeps its port
            def refuse(argv, **kwargs):
                if argv[:3] == ['nft', '-f', '-'] and 'dport 443' in kwargs.get('input', ''):
                    raise tesla.subprocess.CalledProcessError(1, argv)
                return Mock(stdout=json.dumps({'values': SECTIONS}), returncode=0)
            controller = tesla.OfflineChecks(directory, Mock(side_effect=refuse))
            status = {}
            controller.start(NETWORK, NAME, PORT, status, 18443)
            self.assertTrue(controller.active)
            self.assertNotIn('tesla_error', status)
            self.assertFalse(controller.bare)
            self.assertIn('CalledProcessError', controller.page_note)
            controller.restore()

    def test_luci_on_https_only_keeps_port_443(self):
        # uhttpd redirect_https: http://100.96.0.1/ would be sent to https://100.96.0.1/ - the CarPlay page - and
        # LuCI could not be opened from the Wi-Fi at all.
        with tempfile.TemporaryDirectory() as directory:
            def answer(argv, **kwargs):
                if argv[:3] == ['uci', '-q', 'get']:
                    return Mock(stdout='1\n', returncode=0)
                return Mock(stdout=json.dumps({'values': SECTIONS}), returncode=0)
            run = Mock(side_effect=answer)
            controller = tesla.OfflineChecks(directory, run)
            controller.start(NETWORK, NAME, PORT, {}, 18443)
            self.assertTrue(controller.active)
            self.assertFalse(controller.bare)
            self.assertIn('redirect_https', controller.page_note)
            loaded = [c.kwargs['input'] for c in self.calls(run, 'nft') if c.args[0][1:] == ['-f', '-']]
            self.assertEqual(len(loaded), 1, 'the checks only')
            self.assertNotIn('dport 443', loaded[0])
            self.assertIn(['uci', '-q', 'get', 'uhttpd.main.redirect_https'], [c.args[0] for c in self.calls(run, 'uci')])
            controller.restore()

    def test_without_a_viewer_port_nothing_is_added(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Mock(return_value=Mock(stdout=json.dumps({'values': SECTIONS}), returncode=0))
            controller = tesla.OfflineChecks(directory, run)
            controller.start(NETWORK, NAME, PORT, {})
            self.assertFalse(controller.bare)
            self.assertEqual(len([c for c in self.calls(run, 'nft') if c.args[0][1:] == ['-f', '-']]), 1)
            controller.restore()

    def test_lan_once_upstream_switch_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Mock(return_value=Mock(stdout=json.dumps({'values': SECTIONS}), returncode=0))
            controller = tesla.OfflineChecks(directory, run)
            status = {}
            controller.start(NETWORK, NAME, PORT, status)
            controller.refresh(status, online=False)
            self.assertTrue(controller.active)
            self.assertTrue(status['tesla_offline'])
            self.assertEqual(status['tesla_upstream'], 'offline')
            saved = json.loads(controller.path.read_text())
            self.assertEqual(saved['before']['dns.address'], ['/old.example/192.0.2.1'])
            self.assertNotIn('dns.server', saved['before'])
            self.assertEqual(controller.path.stat().st_mode & 0o777, 0o600)
            built = len(run.call_args_list)
            controller.refresh(status, online=True)
            controller.start(NETWORK, NAME, PORT, status)   # a second start changes nothing
            # Upstream changes only update the status: the LAN, DNS and DHCP stay as they are (D4: no
            # answer_tesla_checks choice any more; the checks are answered for as long as the service runs).
            self.assertTrue(controller.active)
            self.assertTrue(status['tesla_offline'])
            self.assertEqual(status['tesla_upstream'], 'online')
            self.assertTrue(controller.path.exists())
            self.assertEqual([c.args[0] for c in run.call_args_list[built:]
                              if c.args[0][0] in ('uci', '/etc/init.d/dnsmasq', 'ip', 'nft')], [])
            controller.restore()   # the service stops
            self.assertFalse(controller.active)
            self.assertFalse(controller.path.exists())
            commands = [c.args[0] for c in run.call_args_list]
            self.assertIn(['uci', 'add_list', 'dhcp.dns.address=/old.example/192.0.2.1'], commands)
            self.assertIn(['nft', 'delete', 'table', 'ip', tesla.TABLE], commands)
            controller.enable(NETWORK, NAME, 18080)
            tesla.OfflineChecks(directory, run).restore()
            self.assertFalse(controller.path.exists(), 'recovery after a supervisor crash')

    def test_status_has_no_reconnect_advice(self):
        with tempfile.TemporaryDirectory() as root:
            run = Mock(return_value=Mock(stdout=json.dumps({'values': SECTIONS}), returncode=0))
            controller = tesla.OfflineChecks(root, run)
            status = {}
            controller.start(NETWORK, NAME, PORT, status)
            controller.refresh(status, online=False)
            self.assertNotIn('tesla_network_change', status)
            self.assertIn('局域网 CarPlay', status['tesla_internet'])
            controller.refresh(status, online=True)
            self.assertEqual(status['tesla_upstream'], 'online')
            self.assertIn('上游在线', status['tesla_internet'])

    def test_baseline_failure_keeps_the_carplay(self):
        with tempfile.TemporaryDirectory() as root:
            run = Mock(return_value=Mock(stdout=json.dumps({'values': SECTIONS}), returncode=0))
            controller = tesla.OfflineChecks(root, run)
            with patch.object(controller, 'enable', side_effect=OSError('synthetic failure')):
                status = {}
                controller.start(NETWORK, NAME, PORT, status)   # must not raise: CarPlay keeps running
            self.assertFalse(controller.active)
            self.assertIn('tesla_error', status)

    def test_failure_restores_saved_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Mock(return_value=Mock(stdout=json.dumps({'values': SECTIONS}), returncode=0))
            controller = tesla.OfflineChecks(directory, run)
            original = controller.command
            def command(argv, **kw):
                if argv[:2] == ['nft', '-f']:
                    raise OSError('synthetic failure')
                return original(argv, **kw)
            with patch.object(controller, 'command', side_effect=command), self.assertRaises(OSError):
                controller.enable(NETWORK, NAME, 18080)
            self.assertFalse(controller.path.exists())
            self.assertFalse(controller.active)

    def test_auto_wan_probe_never_uses_offline_dns_or_tailscale(self):
        interface = {'interface':'wan', 'up':True, 'route':[{'target':'0.0.0.0','mask':0}],
                     'ipv4-address':[{'address':'192.0.2.9'}]}
        run = Mock(return_value=Mock(stdout=json.dumps({'interface':[interface]})))
        connect = Mock(); connect.return_value.__enter__ = Mock(); connect.return_value.__exit__ = Mock()
        self.assertTrue(tesla.wan_available(run, connect))
        self.assertEqual(connect.call_args.kwargs['source_address'], ('192.0.2.9', 0))
        connect.side_effect = OSError('offline')
        self.assertFalse(tesla.wan_available(run, connect))
        interface['interface'] = 'tailscale'
        run.return_value.stdout = json.dumps({'interface':[interface]})
        connect.reset_mock()
        self.assertFalse(tesla.wan_available(run, connect)); connect.assert_not_called()

    def test_wan_counts_as_up_when_only_a_domestic_target_answers(self):
        # 2026-10-15, F50 with a working SIM: the carrier dropped 1.1.1.1:443 (and 8.8.8.8:443) while 223.5.5.5:443
        # answered, so a probe of 1.1.1.1 alone kept the box answering Tesla's checks with no upstream DNS.
        interface = {'interface':'wan', 'up':True, 'route':[{'target':'0.0.0.0','mask':0}],
                     'ipv4-address':[{'address':'192.0.2.9'}]}
        run = Mock(return_value=Mock(stdout=json.dumps({'interface':[interface]})))
        def connect(target, timeout, source_address):
            if target[0] in ('1.1.1.1', '8.8.8.8'):
                raise OSError('timed out')
            conn = Mock(); conn.__enter__ = Mock(return_value=conn); conn.__exit__ = Mock(return_value=False)
            return conn
        self.assertTrue(tesla.wan_available(run, connect))


    def test_dns_logging_is_bounded_and_restores_user_options(self):
        with tempfile.TemporaryDirectory() as root:
            sections = dict(SECTIONS, dns=dict(SECTIONS['dns'], logqueries='0', logfacility='/tmp/previous-dns.log'))
            run = Mock(return_value=Mock(stdout=json.dumps({'values': sections}), returncode=0))
            platform = Mock()
            platform.start.return_value.poll.return_value = None
            controller = tesla.OfflineChecks(root, run, platform)
            status = {}
            controller.start(NETWORK, NAME, PORT, status)
            controller.refresh(status, online=True)
            self.assertEqual(status['tesla_dns_log'], 'recording')
            name, argv = platform.start.call_args.args
            self.assertEqual(name, 'tesla-dns-log')
            self.assertEqual(argv, ['logread','-f','-e','dnsmasq','-F',str(Path(root)/'diag/tesla-dns.log'),'-S','1024'])
            controller.refresh(status, online=False)
            self.assertEqual(platform.start.call_count, 1)
            controller.restore()
            self.assertEqual(platform.stop_child.call_args.args, ('tesla-dns-log',))
            commands = [c.args[0] for c in run.call_args_list]
            self.assertIn(['uci','set','dhcp.dns.logqueries=0'], commands)
            self.assertIn(['uci','set','dhcp.dns.logfacility=/tmp/previous-dns.log'], commands)

    def test_missing_or_exited_dns_logger_does_not_disable_the_lan(self):
        with tempfile.TemporaryDirectory() as root:
            run = Mock(return_value=Mock(stdout=json.dumps({'values': SECTIONS}), returncode=0))
            platform = Mock(); platform.start.side_effect = FileNotFoundError('synthetic missing logger')
            controller = tesla.OfflineChecks(root, run, platform)
            status = {}
            controller.start(NETWORK, NAME, PORT, status)
            self.assertTrue(controller.active)
            self.assertEqual(status['tesla_dns_log'], 'error: FileNotFoundError')
            platform.start.side_effect = None
            platform.start.return_value.poll.return_value = None
            controller.refresh(status, online=False)
            self.assertEqual(status['tesla_dns_log'], 'recording')
            calls = platform.start.call_count
            platform.start.return_value.poll.return_value = 1
            controller.refresh(status, online=False)
            self.assertEqual(platform.start.call_count, calls + 1)
            self.assertTrue(controller.active)
            controller.restore()


if __name__ == '__main__':
    unittest.main()
