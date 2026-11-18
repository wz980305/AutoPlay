"""tesla_openwrt.redirect_rules() and page_rules() in a real kernel, NOT a test on an F50 or a Tesla.

Two throwaway network namespaces joined by a veth pair stand for the box and the car. The box side has the LAN
address 100.96.0.1/24 and the alias 100.96.0.2, loads the rules exactly as the box does (nft -f -), and runs
stand-ins that say which listener a connection reached and on which local port: the viewer, uhttpd on 80 and 443,
and the settings page. The car side connects to each address. What this shows (1.6.9): port 443 of the alias,
AutoPlay's own address that the own name points at, reaches the viewer, which sees its own port (what Ktor calls
localPort); port 80 there still answers the Tesla's checks; the router's address is exactly as before, LuCI on 80
and 443.

Needs root, nft, unshare and pyroute2 (pip install pyroute2); skipped otherwise, and not run by CI:

    cd box && python3 -m unittest discover -s tests/net
"""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import tesla_openwrt as tesla

try:
    from pyroute2 import IPRoute
except ImportError:
    IPRoute = None

BOX, ALIAS, CAR = '100.96.0.1', '100.96.0.2', '100.96.0.50'
SETTINGS = 18080
TARGETS = ((BOX, 443), (BOX, 18443), (BOX, 19500), (BOX, 80), (BOX, SETTINGS), (ALIAS, 80), (ALIAS, 443))


def interface(name, address, prefix, also=()):
    ipr = IPRoute()
    for _ in range(100):
        found = ipr.link_lookup(ifname=name)
        if found:
            break
        time.sleep(0.1)
    else:
        raise SystemExit(f'{name} never arrived')
    ipr.link('set', index=ipr.link_lookup(ifname='lo')[0], state='up')
    ipr.addr('add', index=found[0], address=address, prefixlen=prefix)
    for extra in also:
        ipr.addr('add', index=found[0], address=extra, prefixlen=32)
    ipr.link('set', index=found[0], state='up')


def box(viewer, bare):
    interface('br-lan', BOX, 24, [ALIAS])

    def serve(port, name):
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('0.0.0.0', port))
        listener.listen(16)

        def loop():
            while True:
                connection, _ = listener.accept()
                connection.sendall(f'{name}@{connection.getsockname()[1]}\n'.encode())
                connection.close()
        threading.Thread(target=loop, daemon=True).start()

    for port, name in ((viewer, 'viewer'), (80, 'luci'), (443, 'luci-https'), (SETTINGS, 'settings')):
        serve(port, name)
    subprocess.run(['nft', '-f', '-'], input=tesla.redirect_rules('br-lan', ALIAS, SETTINGS), text=True, check=True)
    if bare:
        subprocess.run(['nft', '-f', '-'], input=tesla.page_rules('br-lan', ALIAS, viewer), text=True, check=True)
    print('ready', flush=True)
    time.sleep(120)


def car():
    interface('wlan0', CAR, 24)
    sys.stdin.readline()   # the box is ready
    for host, port in TARGETS:
        try:
            with socket.create_connection((host, port), 3) as connection:
                answer = connection.makefile().readline().strip()
        except OSError as error:
            answer = type(error).__name__
        print(f'{host}:{port} {answer}', flush=True)


def lab(viewer, bare):
    """{(host, port): 'listener@local port' or the error's name} as the car sees the box."""
    me = [sys.executable, str(Path(__file__).resolve())]
    box_side = subprocess.Popen(['unshare', '-n', *me, 'box', str(viewer), '1' if bare else '0'],
                                stdout=subprocess.PIPE, text=True)
    car_side = subprocess.Popen(['unshare', '-n', *me, 'car'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    ipr = IPRoute()
    try:
        time.sleep(1)   # both are in their namespaces before the cable is handed over
        ipr.link('add', ifname='br-lan', kind='veth', peer={'ifname': 'wlan0'})
        ipr.link('set', index=ipr.link_lookup(ifname='br-lan')[0], net_ns_pid=box_side.pid)
        ipr.link('set', index=ipr.link_lookup(ifname='wlan0')[0], net_ns_pid=car_side.pid)
        if box_side.stdout.readline().strip() != 'ready':
            raise RuntimeError('the box side did not come up')
        out, _ = car_side.communicate('go\n', timeout=60)
    finally:
        ipr.close()
        for side in (box_side, car_side):
            side.kill()
            side.wait()
            for stream in (side.stdin, side.stdout):
                if stream and not stream.closed:
                    stream.close()
    seen = {}
    for line in out.splitlines():
        where, answer = line.split(' ', 1)
        host, port = where.rsplit(':', 1)
        seen[(host, int(port))] = answer
    return seen


@unittest.skipUnless(IPRoute and os.geteuid() == 0 and shutil.which('nft') and shutil.which('unshare'),
                     'needs root, nft, unshare and pyroute2')
class PageRedirectTests(unittest.TestCase):
    def test_the_name_without_a_port_reaches_the_viewer_and_the_router_is_untouched(self):
        seen = lab(18443, True)
        self.assertEqual(seen[(ALIAS, 443)], 'viewer@18443')    # https://<name>/: the name points at the alias
        self.assertEqual(seen[(ALIAS, 80)], f'settings@{SETTINGS}', "the Tesla's checks, as before")
        self.assertEqual(seen[(BOX, 18443)], 'viewer@18443')    # the port itself, as ever
        self.assertEqual(seen[(BOX, 443)], 'luci-https@443', "the router's address: LuCI over HTTPS, as shipped")
        self.assertEqual(seen[(BOX, 80)], 'luci@80')
        self.assertEqual(seen[(BOX, SETTINGS)], f'settings@{SETTINGS}')

    def test_a_port_of_the_owners_own_choice(self):
        seen = lab(19500, True)
        self.assertEqual(seen[(ALIAS, 443)], 'viewer@19500')
        self.assertEqual(seen[(BOX, 19500)], 'viewer@19500')
        self.assertEqual(seen[(BOX, 443)], 'luci-https@443')

    def test_without_the_page_rule_everything_is_as_before_1_6_8(self):
        seen = lab(18443, False)
        self.assertEqual(seen[(ALIAS, 443)], 'luci-https@443')
        self.assertEqual(seen[(BOX, 443)], 'luci-https@443')
        self.assertEqual(seen[(BOX, 18443)], 'viewer@18443')
        self.assertEqual(seen[(ALIAS, 80)], f'settings@{SETTINGS}')


if __name__ == '__main__':
    if sys.argv[1:2] == ['box']:
        box(int(sys.argv[2]), sys.argv[3] == '1')
    elif sys.argv[1:2] == ['car']:
        car()
    else:
        unittest.main()
