"""Never trust a clock earlier than the last one seen (reliability_audit #10)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import clock_floor


class ClockFloorTests(unittest.TestCase):
    def test_moves_the_clock_forward_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            set_calls = []
            now = 1_790_000_000
            self.assertIsNone(clock_floor.apply(tmp, now=now, set_clock=set_calls.append))
            self.assertEqual(clock_floor.read(tmp), now)
            # The next boot's clock is behind (sysfixtime, no NTP): moved to the floor.
            moved = clock_floor.apply(tmp, now=now - 86400 * 30, set_clock=set_calls.append)
            self.assertIn("UTC", moved)
            self.assertEqual(set_calls, [float(now)])
            # A later clock raises the floor and is never pulled back.
            self.assertIsNone(clock_floor.apply(tmp, now=now + 100, set_clock=set_calls.append))
            self.assertEqual(clock_floor.read(tmp), now + 100)
            self.assertEqual(len(set_calls), 1)
            # Garbage or an impossibly early floor is ignored.
            (Path(tmp) / clock_floor.FILE).write_text("12\n")
            self.assertIsNone(clock_floor.read(tmp))
            self.assertFalse(clock_floor.write(tmp, 100))

    def test_touch_is_rate_limited(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock_floor._last_touch[0] = 0.0
            now = 1_790_000_000
            self.assertTrue(clock_floor.touch(tmp, now=now))
            self.assertFalse(clock_floor.touch(tmp, now=now + 10))
            self.assertTrue(clock_floor.touch(tmp, now=now + 3700))

    def test_a_backward_clock_update_does_not_lower_the_saved_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = 1_790_000_000
            self.assertTrue(clock_floor.write(tmp, now))
            self.assertFalse(clock_floor.write(tmp, now - 3600))
            self.assertEqual(clock_floor.read(tmp), now)


if __name__ == '__main__':
    unittest.main()
