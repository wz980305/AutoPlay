"""The LuCI page (luci-app-autoplay's view/autoplay.js) and its Chinese translation: the script parses, and every
text it shows has a translation and every translation a text.

Why (2026-11-18): an apostrophe written into one of its single-quoted strings ended the string early, which would
have stopped the whole AutoPlay page in LuCI from loading; nothing checked the script until then. Needs node for
the parse (skipped without it; CI has it).

Run: python3 -m unittest discover -s openwrt/tests
"""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

LUCI = Path(__file__).resolve().parents[1] / "luci-app-autoplay"
VIEW = LUCI / "htdocs/luci-static/resources/view/autoplay.js"
PO = LUCI / "po/zh_Hans/autoplay.po"


def texts(script):
    """The first argument of each _('...') call, as LuCI looks it up."""
    return {m.group(1).replace("\\'", "'") for m in re.finditer(r"_\('((?:[^'\\]|\\.)*)'", script)}


def msgids(po):
    return {m.group(1).replace('\\"', '"') for m in re.finditer(r'^msgid "((?:[^"\\]|\\.)*)"$', po, re.M)} - {""}


class LuciViewTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_script_parses(self):
        result = subprocess.run(["node", "--check", str(VIEW)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])

    def test_every_text_has_its_translation(self):
        shown, translated = texts(VIEW.read_text()), msgids(PO.read_text())
        self.assertTrue(shown)
        self.assertEqual(sorted(shown - translated), [], "texts without a translation")
        self.assertEqual(sorted(translated - shown), [], "translations no text uses")


if __name__ == "__main__":
    unittest.main()
