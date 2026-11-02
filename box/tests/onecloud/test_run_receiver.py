import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[2] / "scripts/onecloud/run-receiver.py"
spec = importlib.util.spec_from_file_location("run_receiver", HERE)
run_receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_receiver)


class BrowserAccessTest(unittest.TestCase):
    def test_heap_ceiling_follows_the_board_memory(self):
        self.assertEqual(run_receiver.heap_limit("MemTotal:         402316 kB\nMemFree: 1 kB\n"), "-Xmx224m")   # 410 stick
        self.assertEqual(run_receiver.heap_limit("MemTotal:         855012 kB\n"), "-Xmx384m")   # OneCloud
        self.assertEqual(run_receiver.heap_limit("MemTotal:        1897396 kB\n"), "-Xmx384m")   # N1
        self.assertEqual(run_receiver.heap_limit(""), "-Xmx384m")

    def test_token_goes_to_a_file_only_the_box_page_reads_and_the_old_script_goes(self):
        # A script any site could include gave the viewer token away (audit 2026-10-13, A2); the receiver serves
        # receiver-access.json to the box's own page only.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dist = root / "playport/web/dist"
            dist.mkdir(parents=True)
            (dist / "receiver-access.js").write_text("localStorage.setItem('playport-token','old');\n")
            run_receiver.write_browser_access(root, "0123456789abcdef0123456789abcdef", 18080, tesla=False)
            self.assertFalse((dist / "receiver-access.js").exists())
            access = dist / "receiver-access.json"
            self.assertEqual(json.loads(access.read_text()),
                             {"token": "0123456789abcdef0123456789abcdef", "settingsPort": 18080, "audioRouteNavigation": "bluetooth"})
            self.assertEqual(access.stat().st_mode & 0o777, 0o644)
            self.assertEqual(sorted(p.name for p in dist.iterdir()), ["receiver-access.json"])

    def page_flags(self, **flags):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "playport/web/dist").mkdir(parents=True)
            run_receiver.write_browser_access(root, "0123456789abcdef0123456789abcdef", 18080, **flags)
            access = json.loads((root / "playport/web/dist/receiver-access.json").read_text())
            return {key: value for key, value in access.items() if key not in ("token", "settingsPort")}

    def test_tesla_mode_is_the_default_and_brings_the_car_music_with_it(self):
        # D8: the box is Tesla-only; the page reads both flags from receiver-access.json until its own trim.
        self.assertEqual(self.page_flags(), {"carMusic": True, "tesla": True, "audioRouteNavigation": "bluetooth"})
        self.assertEqual(self.page_flags(tesla=False), {"audioRouteNavigation": "bluetooth"}, "a lab receiver without the flag")

    def test_the_audio_route_reaches_the_page_and_is_checked(self):
        # 1.1.0 (uci audio_route_navigation): bluetooth (default) = the receiver offers no audio and the page shows no
        # sound controls; carplay = the page plays prompts.
        self.assertEqual(self.page_flags(audio_route="carplay")["audioRouteNavigation"], "carplay")
        with self.assertRaises(ValueError):
            self.page_flags(audio_route="page")

    def test_rejects_an_unexpected_token(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                run_receiver.write_browser_access(Path(directory), "not-a-token")


class AccessFileTests(unittest.TestCase):
    def test_the_access_file_is_written_only_when_it_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "playport/web/dist").mkdir(parents=True)
            self.assertTrue(run_receiver.write_browser_access(root, "0123456789abcdef0123456789abcdef", 18080))
            self.assertFalse(run_receiver.write_browser_access(root, "0123456789abcdef0123456789abcdef", 18080),
                             "the same token and port: no write on the SD card at every start")
            self.assertTrue(run_receiver.write_browser_access(root, "f" * 32, 18080))

    def test_jvm_options_exit_on_oom_and_write_crash_files_to_state(self):
        source = HERE.read_text()
        self.assertIn("-XX:+ExitOnOutOfMemoryError", source)
        self.assertIn('"-XX:ErrorFile=" + str(crash / "hs_err_%p.log")', source)
        self.assertIn("oom_score_adj", source)
        self.assertIn("--prime-cds", source)


class CdsArchiveTests(unittest.TestCase):
    """A truncated AppCDS archive (JVM restarted mid-dump) is refused on every later start and never replaced."""

    def test_a_refused_archive_is_dropped_so_the_jvm_dumps_a_fresh_one(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "app-cds.jsa").write_bytes(b"x" * 10)
            (state / "cds.log").write_text("[0.012s][info][cds] An error has occurred while processing the shared archive file.\n"
                                           "[0.012s][info][cds] invalid archive: header checksum mismatch\n")
            self.assertTrue(run_receiver.drop_broken_cds_archive(state))
            self.assertFalse((state / "app-cds.jsa").exists())
            (state / "app-cds.jsa").write_bytes(b"x" * 10)
            (state / "cds.log").write_text("[0.5s][info][cds] Mapped static region #0 at base 0x... top 0x...\n")
            self.assertFalse(run_receiver.drop_broken_cds_archive(state))
            self.assertTrue((state / "app-cds.jsa").exists(), "a healthy archive stays")
            (state / "cds.log").unlink()
            self.assertFalse(run_receiver.drop_broken_cds_archive(state), "no log (first start): nothing to judge")


class RedactionTest(unittest.TestCase):
    def test_a_password_the_trace_escaped_is_still_hidden(self):
        # The iAP2 trace prints strings escaped (\" and \\): a password with those characters was not found by a
        # plain replace and stayed in receiver.log (review 2026-10-12).
        password = 'ab"c\\d e'
        line = '  [2] passphrase: "ab\\"c\\\\d e"\n'
        self.assertEqual(run_receiver.redact(line, "f" * 32, password), '  [2] passphrase: "[REDACTED]"\n')

    def test_token_password_and_raw_preview(self):
        token, password = "0123456789abcdef0123456789abcdef", "secret-pass"
        self.assertEqual(run_receiver.redact(f"url ?token={token} pw={password}\n", token, password),
                         "url ?token=[REDACTED] pw=[REDACTED]\n")
        self.assertEqual(run_receiver.redact("  raw-body=[00 01 02]\n", token, password), "  raw-body=[not logged]\n")


if __name__ == "__main__":
    unittest.main()
