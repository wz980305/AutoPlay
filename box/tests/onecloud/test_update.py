"""Online update: signed manifest, downloads from GitHub or a mirror, guards, apk plan, rollback (update.py)."""
import functools
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import update

# OpenSSL 3 signs and checks Ed25519 with -rawin; a Mac's own openssl is LibreSSL.
OPENSSL = next((p for p in (os.environ.get('AUTOPLAY_OPENSSL'), '/opt/homebrew/opt/openssl@3/bin/openssl',
                            '/usr/local/opt/openssl@3/bin/openssl', shutil.which('openssl'))
                if p and Path(p).exists() and 'OpenSSL 3' in subprocess.run([p, 'version'], capture_output=True,
                                                                              text=True).stdout), None)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Server:
    """GitHub stand-in: /gh/<path> serves files (or fails when listed in `down`); /mirror/<full url> serves the same."""

    def __init__(self, root):
        self.root, self.down, self.seen = Path(root), set(), []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                server.seen.append(self.path)
                path = self.path
                if path.startswith('/mirror/'):
                    path = '/gh/' + path.split('/gh/', 1)[1]
                elif path.removeprefix('/gh/') in server.down:
                    return self.send_error(503)
                target = server.root / path.removeprefix('/gh/')
                if not path.startswith('/gh/') or not target.is_file():
                    return self.send_error(404)
                data = target.read_bytes()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.httpd.server_port}/gh/'
        self.mirror = f'http://127.0.0.1:{self.httpd.server_port}/mirror/'

    def put(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ClockTests(unittest.TestCase):
    """The update checker sets a clock months off (no battery clock, no NTP) from a plain-HTTP Date header first."""

    class Reply:
        def __init__(self, date):
            self.headers = {"Date": date}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(self, dates):
        def open_(request, timeout):
            date = dates.pop(0)
            if isinstance(date, Exception):
                raise date
            return self.Reply(date)
        return open_

    def test_a_clock_months_behind_is_set_from_the_date_header(self):
        set_to = []
        offset = update.clock_from_http(urls=("http://a", "http://b"), now=lambda: 1_700_000_000.0,
                                        set_clock=set_to.append,
                                        opener=self.opener(["Tue, 21 Oct 2026 12:00:00 GMT"]))
        self.assertEqual(set_to, [1792584000.0])
        self.assertAlmostEqual(offset, 92_584_000.0)

    def test_a_clock_within_ten_minutes_is_left_alone(self):
        set_to = []
        self.assertEqual(update.clock_from_http(urls=("http://a",), now=lambda: 1792584000.0 - 300,
                                                set_clock=set_to.append,
                                                opener=self.opener(["Tue, 21 Oct 2026 12:00:00 GMT"])), 0)
        self.assertEqual(set_to, [])

    def test_an_unreachable_or_dateless_server_falls_through_to_the_next(self):
        set_to = []
        offset = update.clock_from_http(urls=("http://a", "http://b", "http://c"), now=lambda: 0.0,
                                        set_clock=set_to.append,
                                        opener=self.opener([OSError("offline"), "not a date",
                                                            "Tue, 21 Oct 2026 12:00:00 GMT"]))
        self.assertEqual(set_to, [1792584000.0])
        self.assertTrue(offset > 0)
        self.assertIsNone(update.clock_from_http(urls=("http://a",), set_clock=set_to.append,
                                                 opener=self.opener([OSError("offline")])))


class VersionTests(unittest.TestCase):
    def test_dates_compare_as_numbers(self):
        self.assertTrue(update.newer('2026.10.19.1', '2026.10.19'))
        self.assertTrue(update.newer('2026.10.20', '2026.10.19.1'))
        self.assertTrue(update.newer('2026.11.2', '2026.10.30'))
        self.assertFalse(update.newer('2026.10.19', '2026.10.19'))
        self.assertTrue(update.newer('2026.10.19', None), 'an unknown installed version takes the release')
        self.assertFalse(update.newer('latest', '2026.10.19'), 'a malformed release is never newer')

    def test_a_box_names_its_release_from_the_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(update.bundled_version(root), 'a development build or an older release')
            (root / 'version.txt').write_text('2026.10.20\n')
            self.assertEqual(update.bundled_version(root), '2026.10.20')

    def test_the_installed_version_comes_from_the_package_list(self):
        # `apk info -v` on OpenWrt 25.12; `apk info -v dashplay` prints the description instead (lab, 2026-10-19).
        listing = 'busybox-1.37.0-r6\ndashplay-2026.10.19.1-r1\nautoplay-jre-21.0.12.1-r1\nluci-app-autoplay-0.261019.40345\n'
        self.assertEqual(update.apk_version('dashplay', listing), '2026.10.19.1-r1')
        self.assertEqual(update.apk_version('autoplay-jre', listing), '21.0.12.1-r1')
        self.assertIsNone(update.apk_version('dashplay', 'dashplay: Receives CarPlay from an iPhone\n'))


    def test_the_apk_plan_may_not_touch_the_kernel_kmods_or_bluez(self):
        # Shape of `apk add --upgrade --simulate` on the F50 (2026-10-19).
        plan = ('(1/4) Upgrading dashplay (2026.10.16-r1 -> 2026.10.19.1-r1)\n'
                '(2/4) Upgrading luci-base (26.280.64158~a450f0d -> 26.288.56989~75a306d)\n'
                '(3/4) Upgrading luci-app-autoplay (0.261016.36841 -> 0.261019.40345)\n'
                '(4/4) Upgrading luci-i18n-autoplay-zh-cn (0.261016.36841 -> 0.261019.40345)\nOK: 267.2 MiB\n')
        self.assertEqual(update.forbidden_in_plan(plan), [])
        plan += ('(5/7) Installing kmod-bluetooth (6.12.94-r1)\n(6/7) Installing bluez-daemon (5.83-r1)\n'
                 '(7/7) Upgrading kernel (6.12.94~abc-r1)\n')
        self.assertEqual(update.forbidden_in_plan(plan), ['bluez-daemon', 'kernel', 'kmod-bluetooth'])


@unittest.skipUnless(OPENSSL, 'needs OpenSSL 3')
class SignedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.key, self.pub = self.dir / 'key.pem', self.dir / 'pub.pem'
        subprocess.run([OPENSSL, 'genpkey', '-algorithm', 'ed25519', '-out', str(self.key)], check=True, capture_output=True)
        subprocess.run([OPENSSL, 'pkey', '-in', str(self.key), '-pubout', '-out', str(self.pub)], check=True, capture_output=True)
        self.server = Server(self.dir / 'www')
        self.addCleanup(self.server.close)
        self.root = self.dir / 'opt/autoplay'
        (self.root / 'state/receiver').mkdir(parents=True)
        (self.root / 'identity/offline-mfi').mkdir(parents=True)
        (self.root / 'identity/offline-mfi/identity.pk8').write_bytes(b'secret identity')
        (self.root / 'state/logs/boot1').mkdir(parents=True)
        (self.root / 'state/logs/boot1/receiver.log').write_text('log')
        (self.root / 'state/bluetooth').mkdir()
        (self.root / 'state/bluetooth/pairing').write_text('link key')
        for name, value in (('OPENSSL', OPENSSL), ('LATEST', self.server.base + 'latest/'), ('MIRRORS', ()),
                            ('PREVIOUS_FEED', self.server.base + 'owrt/v{version}/')):
            p = patch.object(update, name, value)
            p.start()
            self.addCleanup(p.stop)

    def sign(self, data):
        (self.dir / 'm').write_bytes(data)
        subprocess.run([OPENSSL, 'pkeyutl', '-sign', '-inkey', str(self.key), '-rawin', '-in', str(self.dir / 'm'),
                        '-out', str(self.dir / 's')], check=True, capture_output=True)
        return (self.dir / 's').read_bytes()

    def publish(self, manifest, signature=None):
        data = json.dumps(manifest).encode()
        self.server.put('latest/autoplay-update.json', data)
        self.server.put('latest/autoplay-update.json.sig', signature if signature is not None else self.sign(data))

    def openwrt_release(self, version, packages, jre='21.0.12.1-r1'):
        """Serve packages {name: bytes} as openwrt-autoplay v<version>; returns the manifest's openwrt part."""
        base = f'owrt/v{version}/'
        entries, sums = {}, []
        for name, data in packages.items():
            file = f'{name}-{version}-r1.apk' if name != 'autoplay-jre' else f'autoplay-jre-{jre}_aarch64_generic.apk'
            self.server.put(base + file, data)
            sums.append(f'{sha(data)}  {file}')
            entries[name] = {'file': file, 'sha256': sha(data), 'size': len(data)}
        sums_data = ('\n'.join(sums) + '\n').encode()
        self.server.put(base + 'SHA256SUMS', sums_data)
        self.server.put(base + 'SHA256SUMS.sig', self.sign(sums_data))
        jre_entry = entries.pop('autoplay-jre', {'file': 'x', 'sha256': '0', 'size': 1})
        return {'base': self.server.base + base, 'packages': entries,
                'jre': {'version': jre, 'files': {'aarch64_generic': jre_entry}}}

    def test_only_a_manifest_signed_by_the_release_key_counts(self):
        manifest = {'format': 1, 'version': '2026.10.20', 'online': True, 'notes': '- x'}
        self.publish(manifest)
        self.assertEqual(update.latest_manifest(self.root, True, self.pub)['version'], '2026.10.20')
        data = json.dumps(manifest).encode()
        self.server.put('latest/autoplay-update.json', data.replace(b'2026.10.20', b'2026.10.21'))   # tampered
        with self.assertRaisesRegex(update.UpdateError, '签名不对'):
            update.latest_manifest(self.root, True, self.pub)
        other = self.dir / 'other.pem'
        subprocess.run([OPENSSL, 'genpkey', '-algorithm', 'ed25519', '-out', str(other)], check=True, capture_output=True)
        subprocess.run([OPENSSL, 'pkey', '-in', str(other), '-pubout', '-out', str(self.dir / 'other.pub')],
                       check=True, capture_output=True)
        self.publish(manifest)
        with self.assertRaisesRegex(update.UpdateError, '签名不对'):
            update.latest_manifest(self.root, True, self.dir / 'other.pub')

    def test_rollback_packages_require_an_authentic_checksum_manifest(self):
        packages = {name: b'old package' for name in update.OPENWRT_PACKAGES}
        self.openwrt_release('2026.10.19.1', packages)
        files = update.previous_packages('2026.10.19.1', (), self.dir / 'cache', key=self.pub)
        self.assertEqual(len(files), 3)
        base = 'owrt/v2026.10.19.1/'
        manifest = self.server.root / base / 'SHA256SUMS'
        # A mirror can replace both an APK and its plain hash; the old signature must still reject it.
        name = 'autoplay-2026.10.19.1-r1.apk'
        self.server.put(base + name, b'malicious package')
        manifest.write_text(manifest.read_text().replace(sha(b'old package') + '  ' + name,
                                                        sha(b'malicious package') + '  ' + name))
        with self.assertRaisesRegex(update.UpdateError, '签名不对'):
            update.previous_packages('2026.10.19.1', (), self.dir / 'tampered', key=self.pub)
        self.assertFalse((self.dir / 'tampered').exists())

    def test_unsigned_legacy_rollback_release_is_rejected(self):
        self.openwrt_release('2026.10.19.1', {name: b'old' for name in update.OPENWRT_PACKAGES})
        (self.server.root / 'owrt/v2026.10.19.1/SHA256SUMS.sig').unlink()
        with self.assertRaisesRegex(update.UpdateError, '已停止'):
            update.previous_packages('2026.10.19.1', (), self.dir / 'unsigned', key=self.pub)
        self.assertFalse((self.dir / 'unsigned').exists())

    def kept_setup(self, kept=''):
        """A stand-in mu300-user-packages that writes down what it was asked to keep, and the box's arch file."""
        tool, asked, index = self.dir / 'mu300-user-packages', self.dir / 'asked', self.dir / 'index'
        tool.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{asked}"\n[ ! -f "{self.dir}/refuse" ]\n')
        tool.chmod(0o755)
        if kept:
            index.write_text(kept)
        arch = self.dir / 'arch'
        arch.write_text('aarch64_generic\n')
        real_path = Path
        patcher = patch.object(update, 'Path', lambda *parts: arch if parts == ('/etc/apk/arch',) else real_path(*parts))
        patcher.start()
        self.addCleanup(patcher.stop)
        return tool, asked, index

    def keep(self, tool, index, versions, **more):
        said = []
        with patch.object(update, 'apk_version', versions.get):
            code = update.keep_for_system_update(self.root, say=said.append, key=self.pub, tool=tool, index=index, **more)
        return code, ' '.join(said)

    def test_the_installed_packages_are_handed_to_the_systems_keep_store(self):
        # mu300-linux's system update installs again only what its feeds have, or a file kept beforehand (1.5.0).
        packages = {name: f'new {name}'.encode() for name in update.OPENWRT_PACKAGES + ('autoplay-jre',)}
        self.openwrt_release('1.5.0', packages, jre='21.0.12.1-r3')
        tool, asked, index = self.kept_setup()
        versions = {'autoplay': '1.5.0-r1', 'autoplay-jre': '21.0.12.1-r3'}
        code, said = self.keep(tool, index, versions, work=self.dir / 'not-there-yet')
        self.assertEqual(code, 0, said)
        names = [Path(line).name for line in asked.read_text().splitlines()]
        self.assertEqual(names, ['keep', 'autoplay-jre-21.0.12.1-r3_aarch64_generic.apk', 'autoplay-1.5.0-r1.apk',
                                 'luci-app-autoplay-1.5.0-r1.apk', 'luci-i18n-autoplay-zh-cn-1.5.0-r1.apk'],
                         'the JRE first: the others need it')
        self.assertIn('已登记 4 个安装包', said)

    def test_what_is_kept_already_is_not_fetched_again_and_local_files_are_used(self):
        packages = {name: f'new {name}'.encode() for name in update.OPENWRT_PACKAGES + ('autoplay-jre',)}
        self.openwrt_release('1.5.0', packages, jre='21.0.12.1-r3')
        versions = {'autoplay': '1.5.0-r1', 'autoplay-jre': '21.0.12.1-r3'}
        everything = ('autoplay-jre 21.0.12.1-r3 a.apk\nautoplay 1.5.0-r1 b.apk\n'
                      'luci-app-autoplay 1.5.0-r1 c.apk\nluci-i18n-autoplay-zh-cn 1.5.0-r1 d.apk\n')
        tool, asked, index = self.kept_setup(everything)
        code, said = self.keep(tool, index, versions)
        self.assertEqual((code, asked.exists()), (0, False), said)
        self.assertIn('已登记', said)
        # After an online update: the JRE is kept, the three new files are in the cache. Nothing is downloaded - the
        # server no longer has them - and a cache file that is not the release's is not used.
        index.write_text(everything.replace('1.5.0-r1', '1.4.3-r1'))
        cache = self.dir / 'cache'; cache.mkdir()
        for name in update.OPENWRT_PACKAGES:
            (cache / f'{name}-1.5.0-r1.apk').write_bytes(packages[name])
            (self.server.root / f'owrt/v1.5.0/{name}-1.5.0-r1.apk').unlink()
        code, said = self.keep(tool, index, versions, have=sorted(cache.glob('*.apk')))
        self.assertEqual(code, 0, said)
        self.assertEqual([Path(line).parent for line in asked.read_text().splitlines()[1:]], [cache] * 3)
        asked.unlink()
        (cache / 'autoplay-1.5.0-r1.apk').write_bytes(b'something else')
        code, said = self.keep(tool, index, versions, have=sorted(cache.glob('*.apk')))
        self.assertEqual((code, asked.exists()), (1, False), 'a wrong local file is fetched instead, and that failed here')
        self.assertIn('没有登记', said)

    def test_keeping_never_raises_and_says_why_it_did_not_happen(self):
        versions = {'autoplay': '1.5.0-r1', 'autoplay-jre': '21.0.12.1-r3'}
        code, said = self.keep(self.dir / 'no-such-tool', self.dir / 'index', versions)
        self.assertEqual(code, 0)
        self.assertIn('不需要这一步', said)
        tool, asked, index = self.kept_setup()
        code, said = self.keep(tool, index, versions)             # this version was never published
        self.assertEqual(code, 1)
        self.assertIn('不是正式发布的版本', said)
        packages = {name: b'x' for name in update.OPENWRT_PACKAGES + ('autoplay-jre',)}
        self.openwrt_release('1.5.0', packages, jre='21.0.12.1-r3')
        (self.dir / 'refuse').write_text('')
        code, said = self.keep(tool, index, versions)             # the tool refused
        self.assertEqual(code, 1)
        self.assertIn('没有成功', said)
        (self.dir / 'refuse').unlink()
        sums = self.server.root / 'owrt/v1.5.0/SHA256SUMS'
        sums.write_text(sums.read_text().replace('autoplay-1.5.0', 'autoplay-9.9.9'))   # tampered list
        asked.unlink()
        code, said = self.keep(tool, index, versions)
        self.assertEqual((code, asked.exists()), (1, False))
        self.assertIn('签名不对', said)
        self.assertEqual(update.kept_versions(self.dir / 'none'), {})

    def test_the_mirror_is_used_when_github_fails(self):
        self.publish({'format': 1, 'version': '2026.10.20', 'online': True})
        self.server.down.add('latest/autoplay-update.json')
        with patch.object(update, 'MIRRORS', (self.server.mirror,)):
            self.assertEqual(update.latest_manifest(self.root, False, self.pub)['version'], '2026.10.20')
        self.assertTrue(any(p.startswith('/mirror/') for p in self.server.seen))
        with self.assertRaisesRegex(update.UpdateError, '下载失败'):
            update.latest_manifest(self.root, False, self.pub)

    def test_a_download_must_match_the_manifest(self):
        self.server.put('f.apk', b'package')
        target = self.dir / 'f.apk'
        update.fetch(self.server.base + 'f.apk', target=target, sha256=sha(b'package'), size=7)
        self.assertEqual(target.read_bytes(), b'package')
        with self.assertRaisesRegex(update.UpdateError, '下载失败'):
            update.fetch(self.server.base + 'f.apk', target=target, sha256=sha(b'other'), size=7)

    def test_check_reports_a_newer_openwrt_release(self):
        self.publish({'format': 1, 'version': '2026.10.20', 'online': True, 'notes': '- 新功能'})
        with patch.object(update, 'apk_version', lambda name: '2026.10.19.1-r1'):
            result = update.check(self.root, True, self.pub)
        self.assertEqual((result['current'], result['latest'], result['available'], result['notes']),
                         ('2026.10.19.1', '2026.10.20', True, '- 新功能'))
        self.assertEqual(json.loads((self.root / 'state/update-check.json').read_text())['latest'], '2026.10.20')
        with patch.object(update, 'apk_version', lambda name: '2026.10.20-r1'):
            self.assertFalse(update.check(self.root, True, self.pub)['available'])



    def test_a_failed_check_is_written_too(self):
        result = update.check(self.root, True, self.pub)   # nothing published
        self.assertIn('下载失败', result['error'])

    def test_no_install_while_carplay_is_in_use_or_when_the_system_changed(self):
        self.publish({'format': 1, 'version': '2026.10.20', 'online': True})
        (self.root / 'state/receiver/phone-presence.json').write_text(json.dumps({'active': '02:00:00:00:00:01'}))
        with patch.object(update, 'apk_version', lambda name: '2026.10.19.1-r1'):
            self.assertEqual(update.install(self.root, True, self.pub), 1)
            self.assertIn('正在使用 CarPlay', json.loads((self.root / 'state/update-status.json').read_text())['message'])
            self.assertIn('正在使用 CarPlay', update.launch(self.root, True))
            (self.root / 'state/receiver/phone-presence.json').write_text('{}')
            self.publish({'format': 1, 'version': '2026.10.20', 'online': False})
            self.assertEqual(update.install(self.root, True, self.pub), 1)
            self.assertIn('刷机包', json.loads((self.root / 'state/update-status.json').read_text())['message'])
        with patch.object(update, 'apk_version', lambda name: '2026.10.20-r1'):
            self.assertEqual(update.install(self.root, True, self.pub), 0)
            self.assertIn('已是最新', json.loads((self.root / 'state/update-status.json').read_text())['message'])

    def openwrt_install(self, simulation_extra='', comes_up=(True,), old_published=True, installed='autoplay'):
        # Larger than fetch()'s default limit, as real packages are (37 MB; lab, 2026-10-19).
        old_names = update.LEGACY_PACKAGES if installed == 'dashplay' else update.OPENWRT_PACKAGES
        if old_published:
            self.openwrt_release('2026.10.19.1', {n: f'old {n}'.encode() * 200000 for n in old_names})
        new = self.openwrt_release('2026.10.20', {n: f'new {n}'.encode() for n in update.OPENWRT_PACKAGES})
        self.publish({'format': 1, 'version': '2026.10.20', 'online': True, 'openwrt': new})
        calls, ups = [], list(comes_up)

        def run(*args, timeout=300):
            if args[0] == OPENSSL:   # the signature is checked for real
                return subprocess.run(list(args), capture_output=True, text=True)
            calls.append(list(args))
            out = ''
            if args[:3] == ('apk', 'add', '--upgrade') and '--simulate' in args:
                out = f'(1/3) Upgrading {installed} (2026.10.19.1-r1 -> 2026.10.20-r1)\n' + simulation_extra
            return subprocess.CompletedProcess(args, 0, out, '')

        arch = self.dir / 'arch'
        arch.write_text('aarch64_generic\n')
        real_path = Path

        def fake_path(*parts):
            return arch if parts == ('/etc/apk/arch',) else real_path(*parts)

        versions = {installed: '2026.10.19.1-r1', 'autoplay-jre': '21.0.12.1-r1'}
        with patch.object(update, 'run', run), patch.object(update, 'apk_version', versions.get), \
                patch.object(update, 'Path', fake_path), patch.object(update, 'settings_port', lambda: 18080), \
                patch.object(update, 'service_up', lambda port, seconds=150: ups.pop(0)), \
                patch.object(update, 'BACKUP', 'backup.tar.gz'), \
                patch.object(update, 'LEGACY_ROOT', str(self.dir / 'legacy')):
            code = update.install(self.root, True, self.pub)
        status_file = self.root / 'state/update-status.json'
        if not status_file.exists():   # a legacy rollback moved the state back to the DashPlay root
            status_file = self.dir / 'legacy/state/update-status.json'
        return code, calls, json.loads(status_file.read_text())

    def test_openwrt_installs_the_three_packages_after_a_clean_plan(self):
        code, calls, status = self.openwrt_install()
        self.assertEqual((code, status['phase']), (0, 'done'), status)
        self.assertIn(['apk', 'update'], calls)
        real = [c for c in calls if c[:3] == ['apk', 'add', '--upgrade'] and '--simulate' not in c]
        self.assertEqual(len(real), 1)
        self.assertEqual(sorted(Path(p).name for p in real[0][4:]),
                         ['autoplay-2026.10.20-r1.apk', 'luci-app-autoplay-2026.10.20-r1.apk',
                          'luci-i18n-autoplay-zh-cn-2026.10.20-r1.apk'], 'no JRE: its version did not change')
        self.assertLess(calls.index(['apk', 'update']), calls.index(real[0]))
        with tarfile.open(self.root.parent / 'backup.tar.gz') as saved:
            names = saved.getnames()
        self.assertIn('identity/offline-mfi/identity.pk8', names)
        self.assertIn('state/bluetooth/pairing', names)
        self.assertFalse([n for n in names if n.startswith('state/logs')], 'logs stay out of the backup')
        self.assertEqual(os.stat(self.root.parent / 'backup.tar.gz').st_mode & 0o777, 0o600)

    def test_openwrt_stops_first_when_the_installed_version_was_never_published(self):
        # F50 on a test build, 2026-10-19: it fetched 35 MB, then stopped with a download error that read like the network.
        code, calls, status = self.openwrt_install(old_published=False)
        self.assertEqual((code, status['phase']), (1, 'failed'))
        self.assertIn('找不到当前版本 2026.10.19.1 的安装包', status['message'])
        self.assertNotIn('网络', status['message'])
        self.assertFalse([p for p in self.server.seen if p.endswith('.apk')], 'stopped before the new release was fetched')
        self.assertFalse([c for c in calls if c[:2] == ['apk', 'add']])

    def test_openwrt_refuses_a_plan_with_kernel_modules(self):
        code, calls, status = self.openwrt_install('(2/3) Installing kmod-bluetooth (6.12.94-r1)\n')
        self.assertEqual((code, status['phase']), (1, 'failed'))
        self.assertIn('kmod-bluetooth', status['message'])
        self.assertFalse([c for c in calls if c[:3] == ['apk', 'add', '--upgrade'] and '--simulate' not in c])

    def test_openwrt_goes_back_when_the_new_version_does_not_come_up(self):
        code, calls, status = self.openwrt_install(comes_up=(False, True))
        self.assertEqual((code, status['phase']), (1, 'failed'))
        self.assertIn('已退回 2026.10.19.1', status['message'])
        back = [c for c in calls if c[:2] == ['apk', 'add'] and '--upgrade' not in c]
        self.assertEqual(sorted(Path(p).name for p in back[0][3:]),
                         ['autoplay-2026.10.19.1-r1.apk', 'luci-app-autoplay-2026.10.19.1-r1.apk',
                          'luci-i18n-autoplay-zh-cn-2026.10.19.1-r1.apk'])

    def test_a_dashplay_box_moves_over_by_removing_the_old_packages_first(self):
        # The transition (TRIM-LOG.md, item 7): different package names, so apk cannot upgrade in place. The old
        # packages go first (their prerm keeps /opt/dashplay/state), the autoplay postinst moves the state over.
        code, calls, status = self.openwrt_install(installed='dashplay')
        self.assertEqual((code, status['phase']), (0, 'done'), status)
        removal = calls.index(['apk', 'del', 'dashplay', 'luci-app-dashplay', 'luci-i18n-dashplay-zh-cn'])
        real = [i for i, c in enumerate(calls) if c[:3] == ['apk', 'add', '--upgrade'] and '--simulate' not in c]
        self.assertEqual(len(real), 1)
        self.assertLess(removal, real[0], 'the old packages are removed before the new ones are installed')
        journal = json.loads((self.root / 'state/update-journal.json').read_text())
        self.assertEqual((journal['phase'], journal['previous']), ('done', '2026.10.19.1'))

    def test_a_dashplay_box_goes_back_to_dashplay_when_autoplay_does_not_come_up(self):
        code, calls, status = self.openwrt_install(installed='dashplay', comes_up=(False, True))
        self.assertEqual((code, status['phase']), (1, 'failed'))
        self.assertIn('已退回 2026.10.19.1', status['message'])
        self.assertIn(['apk', 'del', 'autoplay', 'luci-app-autoplay', 'luci-i18n-autoplay-zh-cn'], calls)
        back = [c for c in calls if c[:2] == ['apk', 'add'] and '--upgrade' not in c]
        self.assertEqual(sorted(Path(p).name for p in back[0][3:]),
                         ['dashplay-2026.10.19.1-r1.apk', 'luci-app-dashplay-2026.10.19.1-r1.apk',
                          'luci-i18n-dashplay-zh-cn-2026.10.19.1-r1.apk'])
        self.assertTrue((self.dir / 'legacy/state/update-journal.json').is_file(), 'the state went back to where the old service reads it')
        self.assertIn('已退回', json.loads((self.dir / 'legacy/state/update-status.json').read_text())['message'])
        self.assertFalse((self.root / 'state').exists(), 'nothing left to stop the next postinst from migrating')
        self.assertFalse((self.root / 'identity').exists())



class GitHub:
    """github.com and its REST API on one loopback server. Release files live at <owner>/<repo>/<tag>/<name>.
    /web/<owner>/<repo>/releases/... is github.com (its download links answer `web_status` when set, 502 as on the
    owner's network); /api/repos/... the API, whose asset download redirects to /cdn/ as GitHub's does."""

    def __init__(self, root, latest):
        self.root, self.latest, self.web_status, self.api_status, self.seen = Path(root), latest, None, None, []
        self.stall, self.released = set(), threading.Event()   # 'api' / 'web' in stall: no answer until released
        github = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send(self, code, data, kind='application/octet-stream'):
                self.send_response(code)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                github.seen.append((self.path, self.headers.get('Accept')))
                parts = self.path.strip('/').split('/')
                if parts[0] in github.stall:   # connected, never answering (1.5.3: GitHub from the owner's network)
                    github.released.wait(20)
                    return   # the caller gave up long ago
                if parts[0] == 'web':                     # web/<o>/<r>/releases/(latest/download|download/<t>)/<n>
                    if github.web_status:
                        return self.send_error(github.web_status)
                    owner, repo, tag, name = parts[1], parts[2], (github.latest if parts[4] == 'latest' else parts[5]), parts[-1]
                    target = github.root / owner / repo / tag / name
                    return self.send(200, target.read_bytes()) if target.is_file() else self.send_error(404)
                if parts[0] == 'api':
                    if github.api_status:
                        return self.send(github.api_status, b'{"message": "API rate limit exceeded"}', 'application/json')
                    if parts[4:6] == ['releases', 'assets']:   # api/repos/<o>/<r>/releases/assets/<t>~<n>
                        if self.headers.get('Accept') != 'application/octet-stream':
                            return self.send(200, b'{"asset": "metadata"}', 'application/json')
                        self.send_response(302)
                        self.send_header('Location', f'http://127.0.0.1:{github.port}/cdn/{parts[2]}/{parts[3]}/' + parts[-1].replace('~', '/'))
                        self.send_header('Content-Length', '0')
                        return self.end_headers()
                    owner, repo = parts[2], parts[3]
                    tag = github.latest if parts[-1] == 'latest' else parts[-1]
                    folder = github.root / owner / repo / tag
                    if not folder.is_dir():
                        return self.send(404, b'{"message": "Not Found"}', 'application/json')
                    base = f'http://127.0.0.1:{github.port}/api/repos/{owner}/{repo}/releases/assets/'
                    assets = [{'name': f.name, 'url': base + f'{tag}~{f.name}', 'browser_download_url': 'unused'}
                              for f in sorted(folder.iterdir())]
                    return self.send(200, json.dumps({'tag_name': tag, 'assets': assets}).encode(), 'application/json')
                if parts[0] == 'cdn':
                    target = github.root.joinpath(*parts[1:])
                    return self.send(200, target.read_bytes()) if target.is_file() else self.send_error(404)
                self.send_error(404)

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def put(self, tag, name, data):
        target = self.root / 'owner' / 'AutoPlay' / tag / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def lookups(self):
        return [p for p, _ in self.seen if p.startswith('/api/') and '/assets/' not in p]

    def close(self):
        self.released.set()
        self.httpd.shutdown()
        self.httpd.server_close()


class Mirror:
    """A mirror (its prefix + the github.com address): answers with the files it holds, by name, or stalls."""

    def __init__(self):
        self.files, self.seen, self.stall, self.released = {}, [], False, threading.Event()
        mirror = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                mirror.seen.append(self.path.rsplit('/', 1)[-1])
                if mirror.stall:
                    mirror.released.wait(20)
                    return   # the caller gave up long ago
                data = mirror.files.get(self.path.rsplit('/', 1)[-1])
                if data is None:
                    return self.send_error(404)
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.prefix = f'http://localhost:{self.httpd.server_port}/'   # its own label, apart from GitHub's 127.0.0.1
        self.label = f'localhost:{self.httpd.server_port}'

    def close(self):
        self.released.set()
        self.httpd.shutdown()
        self.httpd.server_close()


class GitHubApiTests(unittest.TestCase):
    """1.4.2: github.com release links answered 502 on the owner's network while the API's asset download worked."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.key, self.pub = self.dir / 'key.pem', self.dir / 'pub.pem'
        subprocess.run([OPENSSL, 'genpkey', '-algorithm', 'ed25519', '-out', str(self.key)], check=True, capture_output=True)
        subprocess.run([OPENSSL, 'pkey', '-in', str(self.key), '-pubout', '-out', str(self.pub)], check=True, capture_output=True)
        self.github = GitHub(self.dir / 'www', latest='v1.4.2')
        self.addCleanup(self.github.close)
        web = f'http://127.0.0.1:{self.github.port}/web/'
        for name, value in (('OPENSSL', OPENSSL), ('MIRRORS', ()), ('GITHUB', web),
                            ('API', f'http://127.0.0.1:{self.github.port}/api/'),
                            ('LATEST', web + 'owner/AutoPlay/releases/latest/download/'),
                            ('PREVIOUS_FEED', web + 'owner/AutoPlay/releases/download/v{version}/')):
            p = patch.object(update, name, value)
            p.start()
            self.addCleanup(p.stop)
        update._releases.clear()
        self.addCleanup(update._releases.clear)
        p = patch.object(update, '_last_good', None)
        p.start()
        self.addCleanup(p.stop)
        self.root = self.dir / 'opt/autoplay'
        (self.root / 'state').mkdir(parents=True)

    def sign(self, data):
        (self.dir / 'm').write_bytes(data)
        subprocess.run([OPENSSL, 'pkeyutl', '-sign', '-inkey', str(self.key), '-rawin', '-in', str(self.dir / 'm'),
                        '-out', str(self.dir / 's')], check=True, capture_output=True)
        return (self.dir / 's').read_bytes()

    def release(self, tag, files):
        for name, data in files.items():
            self.github.put(tag, name, data)
            if name in ('autoplay-update.json', 'SHA256SUMS'):
                self.github.put(tag, name + '.sig', self.sign(data))

    def test_the_api_downloads_while_github_links_answer_502(self):
        manifest = json.dumps({'format': 1, 'version': '1.4.2', 'online': True}).encode()
        self.release('v1.4.2', {'autoplay-update.json': manifest})
        self.github.web_status = 502
        self.assertEqual(update.latest_manifest(self.root, True, self.pub)['version'], '1.4.2')
        self.assertFalse([p for p, _ in self.github.seen if p.startswith('/web/')], 'github.com was not needed')
        downloads = [accept for p, accept in self.github.seen if '/assets/' in p]
        self.assertEqual(downloads, ['application/octet-stream'] * 2, 'manifest and signature as files, not metadata')
        self.assertEqual(len(self.github.lookups()), 1, 'one release lookup for the manifest and its signature')

    def test_the_way_back_and_the_new_packages_come_through_the_api_too(self):
        packages = {f'{name}-1.4.1-r1.apk': b'old ' + name.encode() for name in update.OPENWRT_PACKAGES}
        sums = ''.join(f'{sha(data)}  {name}\n' for name, data in packages.items()).encode()
        self.release('v1.4.1', {**packages, 'SHA256SUMS': sums})
        self.github.web_status = 502
        files = update.previous_packages('1.4.1', (), self.dir / 'cache', key=self.pub)
        self.assertEqual(sorted(f.name for f in files), sorted(packages))
        target = self.dir / 'new.apk'
        self.github.put('v1.4.2', 'autoplay-1.4.2-r1.apk', b'new package')
        update.fetch(update.GITHUB + 'owner/AutoPlay/releases/download/v1.4.2/autoplay-1.4.2-r1.apk',
                     target=target, sha256=sha(b'new package'), size=11)
        self.assertEqual(target.read_bytes(), b'new package')

    def test_a_refusing_api_falls_back_to_github_and_then_the_mirrors(self):
        manifest = json.dumps({'format': 1, 'version': '1.4.2', 'online': True}).encode()
        self.release('v1.4.2', {'autoplay-update.json': manifest})
        self.github.api_status = 403   # 60 requests an hour per address, shared behind a carrier's NAT
        self.assertEqual(update.latest_manifest(self.root, True, self.pub)['version'], '1.4.2')
        self.assertTrue([p for p, _ in self.github.seen if p.startswith('/web/')])
        self.github.web_status = 502
        with self.assertRaisesRegex(update.UpdateError, '下载失败') as caught:
            update.latest_manifest(self.root, True, self.pub)
        self.assertIn('127.0.0.1', str(caught.exception))

    def test_an_unpublished_version_is_still_not_found(self):
        with self.assertRaises(update.NotFound):
            update.fetch(update.GITHUB + 'owner/AutoPlay/releases/download/v9.9.9/SHA256SUMS')
        self.release('v1.4.1', {'other': b'x'})
        with self.assertRaises(update.NotFound):   # the release exists, the file does not
            update.fetch(update.GITHUB + 'owner/AutoPlay/releases/download/v1.4.1/SHA256SUMS')

    def test_a_lookup_is_not_reused_the_next_day(self):
        self.release('v1.4.2', {'autoplay-update.json': b'one'})
        now = [1000.0]
        url = update.GITHUB + 'owner/AutoPlay/releases/latest/download/autoplay-update.json'
        update.api_download(url, clock=lambda: now[0])
        update.api_download(url, clock=lambda: now[0])
        self.assertEqual(len(self.github.lookups()), 1)
        now[0] += update.RELEASE_CACHE_FOR + 1
        update.api_download(url, clock=lambda: now[0])
        self.assertEqual(len(self.github.lookups()), 2)

    def test_other_addresses_are_left_alone(self):
        self.assertIsNone(update.api_download('https://ghfast.top/https://github.com/o/r/releases/latest/download/x'))
        self.assertEqual([label for label, _, _ in update.sources('http://192.168.1.2:8000/x', ('https://m/',))],
                         ['192.168.1.2:8000', 'm'])
        self.assertEqual([label for label, _, _ in update.sources('http://192.168.1.2:8000/x', ('https://m/',), 'm')],
                         ['m', '192.168.1.2:8000'], 'the place that delivered last time first')

    # 1.5.3: on the owner's network 「正在检查更新」 ran past the page's 90 s. Each place had 30 s per connection and per
    # file, one after another: where GitHub stalled, the mirror answered after two minutes.

    def mirror(self, files):
        mirror = Mirror()
        self.addCleanup(mirror.close)
        mirror.files.update(files)
        p = patch.object(update, 'MIRRORS', (mirror.prefix,))
        p.start()
        self.addCleanup(p.stop)
        return mirror

    def signed(self, version):
        manifest = json.dumps({'format': 1, 'version': version, 'online': True}).encode()
        return {'autoplay-update.json': manifest, 'autoplay-update.json.sig': self.sign(manifest)}

    def test_a_stalled_github_does_not_hold_the_check(self):
        mirror = self.mirror(self.signed('1.5.3'))
        self.github.stall.update({'api', 'web'})
        started = time.monotonic()
        self.assertEqual(update.latest_manifest(self.root, True, self.pub, limit=10, head_start=0.3)['version'], '1.5.3')
        self.assertLess(time.monotonic() - started, 3, 'the mirror after two head starts, not after 30 s per place')
        self.assertEqual(update._last_good, mirror.label)
        # The downloads that follow (an install) ask that place first, so they do not wait on GitHub either.
        started, target = time.monotonic(), self.dir / 'pkg.apk'
        mirror.files['autoplay-1.5.3-r1.apk'] = b'new package'
        update.fetch(update.GITHUB + 'owner/AutoPlay/releases/download/v1.5.3/autoplay-1.5.3-r1.apk', (mirror.prefix,),
                     target=target, sha256=sha(b'new package'), size=11)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(target.read_bytes(), b'new package')

    def test_the_whole_check_gives_up_at_its_limit(self):
        mirror = self.mirror(self.signed('1.5.3'))
        mirror.stall = True
        self.github.stall.update({'api', 'web'})
        started = time.monotonic()
        with self.assertRaisesRegex(update.UpdateError, '下载失败：1 秒内没有拿到更新清单') as caught:
            update.latest_manifest(self.root, True, self.pub, limit=1, head_start=0.2)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(str(caught.exception).count('没有回应'), 3, 'the API, github.com and the mirror, each named')
        self.assertEqual(update.CHECK_LIMIT, 60, "the owner's figure")

    def test_a_quick_wrong_answer_does_not_beat_a_slower_right_one(self):
        manifest = json.dumps({'format': 1, 'version': '1.5.3', 'online': True}).encode()
        self.release('v1.5.3', {'autoplay-update.json': manifest})
        self.github.latest = 'v1.5.3'
        mirror = self.mirror({'autoplay-update.json': manifest.replace(b'1.5.3', b'9.9.9'),
                              'autoplay-update.json.sig': self.sign(manifest)})
        with patch.object(update, '_last_good', mirror.label):   # asked first, answers at once, and wrongly
            self.assertEqual(update.latest_manifest(self.root, True, self.pub, limit=10, head_start=0.3)['version'],
                             '1.5.3')
            self.assertEqual(update._last_good, f'127.0.0.1:{self.github.port}')
        self.assertIn('autoplay-update.json', mirror.seen)

    def test_the_manifest_and_its_signature_come_from_one_place(self):
        manifest = json.dumps({'format': 1, 'version': '1.5.3', 'online': True}).encode()
        self.github.put('v1.5.3', 'autoplay-update.json', manifest)   # no signature on GitHub
        self.github.latest = 'v1.5.3'
        mirror = self.mirror(self.signed('1.5.3'))
        self.assertEqual(update.latest_manifest(self.root, True, self.pub, limit=10, head_start=0.3)['version'], '1.5.3')
        self.assertEqual(mirror.seen, ['autoplay-update.json', 'autoplay-update.json.sig'])

    def test_the_page_shows_checking_until_the_check_has_given_up(self):
        import settings_page
        self.assertGreater(settings_page.CHECK_SHOWN_FOR, update.CHECK_LIMIT)
        self.assertLessEqual(settings_page.CHECK_SHOWN_FOR, update.CHECK_LIMIT + 30)


class ServiceUpTests(unittest.TestCase):
    HEALTHY = {"system": {"state": "ok"}, "bluetooth": {"state": "on"}}

    def service_up(self, answers, statuses, seconds=5):
        answers, statuses = iter(answers), iter(statuses)
        last = {}
        def connect(*_):
            if not next(answers, False):
                raise OSError('refused')
            return io.BytesIO()
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / 'status.json'
            def sleep(_):
                nonlocal last
                last = next(statuses, last)
                status.write_text(json.dumps(last))
            sleep(0)
            with patch.object(update.socket, 'create_connection', connect):
                return update.service_up(18080, seconds=seconds, steady=0, status_file=status, sleep=sleep)

    def test_the_page_must_still_answer_a_while_later(self):
        # Up at once, then gone: a crash after the start.
        self.assertFalse(self.service_up([True, False, False, False], [self.HEALTHY], seconds=0.05))
        self.assertTrue(self.service_up([False, True, True], [self.HEALTHY]))

    def test_health_means_receiver_up_and_bluetooth_powered(self):
        # reliability_audit #8: a version whose JVM or Bluetooth fails must not pass as "up".
        self.assertFalse(update.healthy({"system": {"state": "restarting"}, "bluetooth": {"state": "on"}}, True))
        self.assertFalse(update.healthy({"system": {"state": "ok"}, "bluetooth": {"state": "failed"}}, True))
        self.assertFalse(update.healthy(self.HEALTHY, False))
        self.assertFalse(update.healthy({}, True), "no status file: the supervisor never got that far")
        self.assertTrue(update.healthy(self.HEALTHY, True))
        self.assertFalse(self.service_up([True, True, True], [{"system": {"state": "starting"}, "bluetooth": {"state": "starting"}}],
                                         seconds=0.05))
        self.assertTrue(self.service_up([True, True, True, True],
                                        [{"system": {"state": "starting"}, "bluetooth": {"state": "on"}}, self.HEALTHY]))


class RecoveryTests(unittest.TestCase):
    """An update cut by a power loss is finished or rolled back at the next start (reliability_audit #8)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'dashplay'; (self.root / 'state').mkdir(parents=True)
        self.cache = Path(tmp.name) / update.CACHE; self.cache.mkdir()
        self.previous = self.cache / 'previous' / 'dashplay-2026.10.25-r1.apk'
        self.previous.parent.mkdir(); self.previous.write_bytes(b'old')

    def journal(self, **fields):
        update.write_journal(self.root, **fields)

    def test_clean_journal_does_nothing(self):
        self.assertIsNone(update.recover(self.root, say=lambda _: None, version='2026.10.25'))
        self.journal(phase='done', target='2026.11.1', previous='2026.10.25')
        self.assertIsNone(update.recover(self.root, say=lambda _: None, version='2026.11.1'))

    def test_an_install_that_finished_before_the_cut_is_marked_done(self):
        self.journal(phase='installing', target='2026.11.1', previous='2026.10.25', previous_files=[str(self.previous)])
        text = update.recover(self.root, say=lambda _: None, version='2026.11.1', run_apk=lambda files: self.fail('no rollback'))
        self.assertIn('completed', text)
        self.assertEqual(update.read(update.journal_path(self.root))['phase'], 'done')

    def test_a_half_installed_update_is_rolled_back_from_the_cache(self):
        self.journal(phase='installing', target='2026.11.1', previous='2026.10.25', previous_files=[str(self.previous)])
        calls = []
        text = update.recover(self.root, say=lambda _: None, version='2026.10.25',
                              run_apk=lambda files: calls.append(files) or True)
        self.assertIn('rolled back', text)
        self.assertEqual(calls, [[str(self.previous)]])
        self.assertEqual(update.read(update.journal_path(self.root))['phase'], 'rolled-back')
        self.assertIn('断电', update.read(self.root / 'state/update-status.json')['message'])

    def test_missing_cache_is_reported_not_crashed(self):
        self.previous.unlink()
        self.journal(phase='restoring', target='2026.11.1', previous='2026.10.25', previous_files=[str(self.previous)])
        said = []
        text = update.recover(self.root, say=said.append, version='2026.10.25', run_apk=lambda files: self.fail('nothing to add'))
        self.assertIn('nothing to roll back', text)
        self.assertEqual(update.read(update.journal_path(self.root))['phase'], 'failed')
        self.assertTrue(said)


class LaunchTests(unittest.TestCase):
    def test_a_launch_that_cannot_start_says_so_and_leaves_nothing_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def missing(*a, timeout=30):
                raise FileNotFoundError(2, 'No such file or directory', a[0])
            with patch.object(update, 'run', missing):
                self.assertIn('无法启动升级', update.launch(root, True))
            status = json.loads((root / 'state/update-status.json').read_text())
            self.assertEqual(status['phase'], 'failed')
            self.assertFalse(update.running(root), 'the next try is not refused')

    def test_launch_starts_the_separate_service_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            with patch.object(update, 'run', lambda *a, timeout=30: calls.append(a) or subprocess.CompletedProcess(a, 0, '', '')):
                self.assertIn('已开始升级', update.launch(root, True))
                # A procd service for this run over ubus: no init script that installing a package would start.
                self.assertEqual([c[:4] for c in calls], [('ubus', 'call', 'service', 'delete'), ('ubus', 'call', 'service', 'set')])
                service = json.loads(calls[1][4])
                self.assertEqual(service['name'], 'autoplay-update')
                self.assertEqual(service['instances']['update']['command'][2:], ['install', '--root', str(root)])
                self.assertIn('正在升级', update.launch(root, True), 'a second click while it runs starts nothing')
                self.assertEqual(len(calls), 2)


class ManifestTests(unittest.TestCase):
    def test_the_release_manifest_lists_every_download_with_its_hash(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('make_update_manifest', Path(__file__).resolve().parents[2]
                                                      / 'scripts/make-update-manifest.py')
        maker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(maker)
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp)
            (release / 'openwrt').mkdir()
            (release / 'autoplay').mkdir()
            for name in ('autoplay-2026.10.20-r1.apk', 'luci-app-autoplay-0.261020.1.apk',
                         'luci-i18n-autoplay-zh-cn-0.261020.1.apk', 'autoplay-jre-21.0.12.1-r1_aarch64_generic.apk',
                         'autoplay-jre-21.0.12.1-r1_x86_64.apk'):
                (release / 'openwrt' / name).write_bytes(name.encode())
            with tarfile.open(release / 'autoplay/autoplay-bundle-2026.10.20.tar', 'w') as tar:
                for name, data in (('./supervisor.py', b'program'), ('./state/receiver/x', b'owner'),
                                   ('./identity/offline-mfi/identity.pk8', b'secret')):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            value = maker.manifest('2026.10.20', '- 新功能', release, 'owner', True)
            two = maker.manifest('2026.10.20', '- 新功能', release, 'owner', True, feed_repo='openwrt-autoplay')
            size = (release / 'autoplay/autoplay-bundle-2026.10.20.tar').stat().st_size
        self.assertEqual((value['format'], value['version'], value['online'], value['notes']), (1, '2026.10.20', True, '- 新功能'))
        self.assertEqual(value['openwrt']['packages']['autoplay']['sha256'], sha(b'autoplay-2026.10.20-r1.apk'))
        self.assertEqual(value['openwrt']['jre']['version'], '21.0.12.1-r1')
        self.assertEqual(sorted(value['openwrt']['jre']['files']), ['aarch64_generic', 'x86_64'])
        self.assertEqual(value['openwrt']['base'], 'https://github.com/owner/AutoPlay/releases/download/v2026.10.20/',
                         'one repository: the packages sit in the same release as the manifest (1.3.1)')
        self.assertEqual(value['bundle']['base'], value['openwrt']['base'])
        self.assertEqual(two['openwrt']['base'], 'https://github.com/owner/openwrt-autoplay/releases/download/v2026.10.20/')
        self.assertEqual(value['bundle']['file'], 'autoplay-bundle-2026.10.20.tar')
        self.assertEqual(value['bundle']['size'], size)


if __name__ == '__main__':
    unittest.main()
