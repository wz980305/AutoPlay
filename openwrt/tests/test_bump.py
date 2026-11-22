"""openwrt/scripts/bump-autoplay.sh on a copy of the package Makefile: the version numbers it takes and what it writes."""
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

OPENWRT = Path(__file__).resolve().parents[1]


class BumpTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tree = Path(tmp.name)
        (self.tree / "scripts").mkdir()
        (self.tree / "autoplay").mkdir()
        shutil.copy(OPENWRT / "scripts/bump-autoplay.sh", self.tree / "scripts/bump-autoplay.sh")
        shutil.copy(OPENWRT / "autoplay/Makefile", self.tree / "autoplay/Makefile")
        self.bundle = self.tree / "autoplay-bundle.tar"
        with tarfile.open(self.bundle, "w") as tar:
            data = b"# the supervisor\n"
            info = tarfile.TarInfo("./supervisor_openwrt.py")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    def bump(self, version, bundle=None):
        return subprocess.run(["sh", str(self.tree / "scripts/bump-autoplay.sh"), version, str(bundle or self.bundle)],
                              capture_output=True, text=True)

    def test_an_autoplay_version_is_taken(self):
        # Review 2026-11-22: only DashPlay's dates (2026.10.12) were, so every AutoPlay release was refused.
        done = self.bump("1.7.0")
        self.assertEqual(done.returncode, 0, done.stderr)
        makefile = (self.tree / "autoplay/Makefile").read_text()
        self.assertIn("\nPKG_VERSION:=1.7.0\n", makefile)
        self.assertIn("\nPKG_RELEASE:=1\n", makefile)
        self.assertIn("\nPKG_HASH:=" + hashlib.sha256(self.bundle.read_bytes()).hexdigest() + "\n", makefile)
        self.assertEqual(self.bump("2026.10.12").returncode, 0, "DashPlay's dates still fit")

    def test_what_is_no_version_or_no_bundle_changes_nothing(self):
        before = (self.tree / "autoplay/Makefile").read_text()
        for version in ("v1.7.0", "1", "1.7.0-rc1", "1.7.0;x", "1.7.0 2"):
            done = self.bump(version)
            self.assertEqual(done.returncode, 1, version)
            self.assertIn("version like 1.6.9", done.stderr)
        other = self.tree / "other.tar"
        with tarfile.open(other, "w") as tar:
            tar.addfile(tarfile.TarInfo("./readme.txt"), io.BytesIO(b""))
        done = self.bump("1.7.0", other)
        self.assertEqual(done.returncode, 1)
        self.assertIn("is not an AutoPlay program bundle", done.stderr)
        self.assertEqual((self.tree / "autoplay/Makefile").read_text(), before)


if __name__ == "__main__":
    unittest.main()
