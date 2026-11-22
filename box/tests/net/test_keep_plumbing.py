"""tesla_openwrt.OfflineChecks.keep() against a real kernel, NOT a test on an F50.

In a throwaway network namespace an empty bridge stands for br-lan (100.96.0.1/24). keep() is run with the real `ip`
and `nft`: it must find the alias address and the table missing and put them back, do nothing when they are there,
and put back each of them again after `ip addr flush` (what netifd does to a device it brings up again) and
`nft flush ruleset`. What this shows (review 2026-11-22): what the commands print is read rightly on this ip and nft.

Needs root, nft and unshare; skipped otherwise:

    cd box && python3 -m unittest discover -s tests/net
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import tesla_openwrt as tesla

DEVICE, BOX, ALIAS, SETTINGS, VIEWER = 'br-lan', '100.96.0.1', '100.96.0.2', 18080, 18443


def sh(*argv, check=True):
    return subprocess.run(argv, capture_output=True, text=True, check=check)


def inside():
    """Runs in the namespace; prints one JSON object of what was seen."""
    sh('ip', 'link', 'add', DEVICE, 'type', 'bridge')   # what br-lan is on the box
    sh('ip', 'addr', 'add', BOX + '/24', 'dev', DEVICE)
    sh('ip', 'link', 'set', DEVICE, 'up')
    seen = {}
    with tempfile.TemporaryDirectory() as directory:
        checks = tesla.OfflineChecks(directory)
        # As enable() leaves it, without the uci and dnsmasq half that has no place in a namespace.
        checks.active, checks.page_host = True, ALIAS
        checks.plumbing = (DEVICE, ALIAS, SETTINGS, VIEWER)

        def state():
            return {'address': tesla.has_address(sh('ip', '-4', '-o', 'addr', 'show', 'dev', DEVICE).stdout, ALIAS),
                    'table': sh('nft', 'list', 'table', 'ip', tesla.TABLE, check=False).stdout}
        seen['first'] = checks.keep()
        seen['after_first'] = state()
        seen['again'] = checks.keep()
        sh('ip', 'addr', 'flush', 'dev', DEVICE)            # netifd bringing the device up again...
        sh('ip', 'addr', 'add', BOX + '/24', 'dev', DEVICE)   # ...with the address it knows of
        seen['after_flush'] = checks.keep()
        seen['address_back'] = state()['address']
        sh('nft', 'flush', 'ruleset')
        seen['after_ruleset_flush'] = checks.keep()
        seen['table_back'] = state()['table']
        seen['last'] = checks.keep()
        seen['rules_once'] = state()['table'].count('redirect to')
    print(json.dumps(seen))


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('nft') and shutil.which('unshare') and shutil.which('ip'),
                     'needs root, ip, nft and unshare')
class KeepPlumbingTests(unittest.TestCase):
    def test_what_was_taken_is_put_back_and_nothing_else_is_touched(self):
        done = subprocess.run(['unshare', '-n', sys.executable, str(Path(__file__).resolve()), 'inside'],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        seen = json.loads(done.stdout)
        self.assertEqual(seen['first'], ['address', 'rules'])
        self.assertTrue(seen['after_first']['address'])
        self.assertIn(f'ip daddr {ALIAS} tcp dport 80 redirect to :{SETTINGS}', seen['after_first']['table'])
        self.assertIn(f'ip daddr {ALIAS} tcp dport 443 redirect to :{VIEWER}', seen['after_first']['table'])
        self.assertEqual(seen['again'], [], 'in place: nothing is done')
        self.assertEqual(seen['after_flush'], ['address'])
        self.assertTrue(seen['address_back'])
        self.assertEqual(seen['after_ruleset_flush'], ['rules'])
        self.assertIn('dport 443 redirect', seen['table_back'])
        self.assertEqual(seen['last'], [])
        self.assertEqual(seen['rules_once'], 2, 'each rule once, however often it was looked at')


if __name__ == '__main__':
    if sys.argv[1:2] == ['inside']:
        inside()
    else:
        unittest.main()
