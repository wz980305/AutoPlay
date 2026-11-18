#!/usr/bin/env python3
"""The receiver's real web server behind the box's real redirect rules, asked the way a browser asks it through
https://<name>/ (1.6.8; since 1.6.9 the name points at the alias). A lab run, NOT a test on an F50 or a Tesla,
and not run by CI.

Two throwaway network namespaces joined by a veth pair. The "box" has 100.96.0.1/24 and the alias 100.96.0.2,
loads redirect_rules() and page_rules() on the alias as the box does, and runs the receiver's WebHub on Ktor/Netty with TLS on 18443 (LabServeTest in
receiver/server: the real routes, no CarPlay). The "car" asks with curl and a raw WebSocket handshake: the page, the
token file, a settings POST over HTTP/2 and HTTP/1.1, and the picture channel, each through the name without a port
(443) and through the port itself; then the same from another site, a plain-http origin, another port and with a
wrong token, which must all be refused.

Why it exists: over HTTP/2 a browser sends `:authority: name` for https://name/ and Ktor 3.6 then reports the port
the server listens on, not 443; until 1.6.8 WebHub.ownPage refused such a POST as another site's (403). Run it again
after a Ktor upgrade.

    cd receiver && ./gradlew :server:test        # once, with the network: the build's packages
    sudo python3 box/tests/net/receiver_lab.py   # root, nft, unshare, curl with HTTP/2, pyroute2 (pip)

Prints one line per request and ends with 0 when every answer is the expected one.
"""
import base64
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'box/scripts/onecloud'))
import tesla_openwrt as tesla   # noqa: E402

BOX, ALIAS, CAR, NAME = '100.96.0.1', '100.96.0.2', '100.96.0.50', 'car.example.com'
TOKEN = '0123456789abcdef0123456789abcdef'   # LabServeTest's
VIEWER, SETTINGS = 18443, 18080


def interface(name, address, also=()):
    from pyroute2 import IPRoute
    ipr = IPRoute()
    for _ in range(200):
        found = ipr.link_lookup(ifname=name)
        if found:
            break
        time.sleep(0.1)
    else:
        raise SystemExit(f'{name} never arrived')
    ipr.link('set', index=ipr.link_lookup(ifname='lo')[0], state='up')
    ipr.addr('add', index=found[0], address=address, prefixlen=24)
    for extra in also:
        ipr.addr('add', index=found[0], address=extra, prefixlen=32)
    ipr.link('set', index=found[0], state='up')
    ipr.close()


def box():
    interface('br-lan', BOX, [ALIAS])
    subprocess.run(['nft', '-f', '-'], input=tesla.redirect_rules('br-lan', ALIAS, SETTINGS), text=True, check=True)
    subprocess.run(['nft', '-f', '-'], input=tesla.page_rules('br-lan', ALIAS, VIEWER), text=True, check=True)
    env = dict(os.environ, AUTOPLAY_LAB_PORT=str(VIEWER), AUTOPLAY_LAB_SECONDS=os.environ.get('LAB_SECONDS', '60'))
    os.chdir(REPO / 'receiver')
    # No network in here: the packages are those of an earlier build. cleanTest: the task would otherwise be up to date.
    os.execvpe('./gradlew', ['./gradlew', '--no-daemon', '--offline', ':server:cleanTest', ':server:test', '--tests',
                             'com.playport.server.LabServeTest', '--console=plain', '-i'], env)


def curl(url, *extra):
    where = url.split('/')[2]
    port = int(where.split(':')[1]) if ':' in where else 443
    out = subprocess.run(['curl', '-sk', '--noproxy', '*', '-m', '8', '-o', '/dev/null', '-w', '%{http_version} %{http_code}',
                          '--resolve', f'{NAME}:{port}:{ALIAS}', *extra, url], capture_output=True, text=True).stdout
    return out or 'no answer'


def websocket(port, origin, host):
    """The handshake a browser makes for the picture channel, and the first frame: the hub's hello, or a close."""
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE   # the lab's self-signed certificate
    context.set_alpn_protocols(['http/1.1'])
    connection = context.wrap_socket(socket.create_connection((ALIAS, port), 5), server_hostname=NAME)
    key = base64.b64encode(os.urandom(16)).decode()
    connection.sendall((f'GET /ws?token={TOKEN}&page=lab HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n'
                        f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                        f'Origin: {origin}\r\n\r\n').encode())
    connection.settimeout(4)
    data = b''
    try:
        while b'\r\n\r\n' not in data:
            data += connection.recv(4096)
        head, rest = data.split(b'\r\n\r\n', 1)
        status = head.split(b'\r\n')[0].decode().split(' ')[1]
        while len(rest) < 4:
            rest += connection.recv(4096)
        if rest[0] & 0x0f == 8:
            return f'{status} closed {struct.unpack("!H", rest[2:4])[0]}'
        return f'{status} ' + ('hello' if b'"type":"hello"' in rest else 'frame')
    except socket.timeout:
        return 'no frame'
    finally:
        connection.close()


def car():
    interface('wlan0', CAR)
    for _ in range(150):
        if curl(f'https://{NAME}/api/display').endswith(' 200'):
            break
        time.sleep(2)
    else:
        print('the server never answered')
        return 1
    body = ['-X', 'POST', '-H', 'Content-Type: application/json', '-d', '{"enabled":false,"datum":"auto"}']
    same = ('-H', 'Sec-Fetch-Site: same-origin')

    def post(base, origin, *more, token=TOKEN, version='--http2'):
        return curl(f'{base}/api/location?token={token}', version, *body, '-H', f'Origin: {origin}', *more)

    bare, direct = f'https://{NAME}', f'https://{NAME}:{VIEWER}'
    # A POST that passes the own-page check ends in 503 here: the lab has no CarPlay to switch the location of.
    rows = [
        ('page, no port, HTTP/2', curl(bare + '/', '--http2'), '2 200'),
        ('page, no port, HTTP/1.1', curl(bare + '/', '--http1.1'), '1.1 200'),
        ('token file, no port, HTTP/2', curl(bare + '/receiver-access.json', '--http2', *same), '2 200'),
        ('token file asked by another site', curl(bare + '/receiver-access.json', '--http2', '-H', 'Sec-Fetch-Site: cross-site'), '2 403'),
        ('setting, no port, HTTP/2', post(bare, bare, *same), '2 503'),
        ('setting, no port, HTTP/1.1', post(bare, bare, *same, version='--http1.1'), '1.1 503'),
        ('setting, no port, HTTP/2, an older browser (no Sec-Fetch-Site)', post(bare, bare), '2 503'),
        ('setting, port 18443, HTTP/2', post(direct, direct, *same), '2 503'),
        ('setting, port 18443, HTTP/1.1', post(direct, direct, *same, version='--http1.1'), '1.1 503'),
        ('setting from another site', post(bare, 'https://evil.example'), '2 403'),
        ('setting from another site (Sec-Fetch-Site)', post(bare, bare, '-H', 'Sec-Fetch-Site: cross-site'), '2 403'),
        ('setting from the plain-http name', post(bare, f'http://{NAME}'), '2 403'),
        ('setting from another port of the name', post(bare, f'https://{NAME}:8443'), '2 403'),
        ('setting with a wrong token', post(bare, bare, *same, token='f' * 32), '2 403'),
        ('picture channel, no port', websocket(443, bare, NAME), '101 hello'),
        ('picture channel, port 18443', websocket(VIEWER, direct, f'{NAME}:{VIEWER}'), '101 hello'),
        ('picture channel from another site', websocket(443, 'https://evil.example', NAME), '101 closed 1008'),
    ]
    wrong = 0
    for label, answer, expected in rows:
        wrong += answer != expected
        print(f'{"ok " if answer == expected else "NOT"} {label}: {answer}' + ('' if answer == expected else f' (expected {expected})'), flush=True)
    return 1 if wrong else 0


def main():
    from pyroute2 import IPRoute
    me = [sys.executable, str(Path(__file__).resolve())]
    with open(os.environ.get('LAB_LOG', os.devnull), 'w') as log:
        box_side = subprocess.Popen(['unshare', '-n', *me, 'box'], stdout=log, stderr=subprocess.STDOUT)
        car_side = subprocess.Popen(['unshare', '-n', *me, 'car'])
        time.sleep(1)   # both are in their namespaces before the cable is handed over
        ipr = IPRoute()
        try:
            ipr.link('add', ifname='br-lan', kind='veth', peer={'ifname': 'wlan0'})
            ipr.link('set', index=ipr.link_lookup(ifname='br-lan')[0], net_ns_pid=box_side.pid)
            ipr.link('set', index=ipr.link_lookup(ifname='wlan0')[0], net_ns_pid=car_side.pid)
            return car_side.wait(timeout=600)
        finally:
            ipr.close()
            car_side.kill()
            box_side.wait(timeout=300)   # the server ends by itself after LAB_SECONDS


if __name__ == '__main__':
    role = sys.argv[1] if len(sys.argv) > 1 else ''
    if role == 'box':
        box()
    else:
        sys.exit(car() if role == 'car' else main())
