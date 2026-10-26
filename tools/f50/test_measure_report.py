"""Unit test for measure-report.py with a synthetic CSV.

    python3 -m unittest tools/f50/test_measure_report.py
"""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("measure_report", os.path.join(HERE, "measure-report.py"))
mr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mr)

HEADER = ("time,uptime,load1,mem_avail_kb,jvm_pid,jvm_rss_kb,stations,ss_conns,ss_rtt_max_ms,ss_retrans_d,ss_unacked_max,"
          "wlan0_rx_bytes_d,wlan0_tx_bytes_d,cpu0_busy,cpu0_softirq,cpu1_busy,cpu1_softirq,"
          "policy0_cur_khz,policy0_max_khz,policy4_cur_khz,policy4_max_khz,"
          "tz_soc_thmzone_mc,tz_board_mc,cd0_thermal_cpufreq_0,cd1_thermal_cpufreq_1,"
          "irq53_sprd_pcie_d,irq53_sprd_pcie_cpu0_d")


def synthetic_rows(n=60, interval=10):
    """60 samples = 10 minutes. The SoC warms from 60 to 90 C in the first 30 samples and stays hot; the cpufreq cooling
    device engages for the last 12 samples (2 minutes); CPU0 busy ramps 0..59."""
    rows = []
    for i in range(n):
        soc = 60000 + min(i, 30) * 1000           # 60 C .. 90 C
        board = 40000 + i * 100
        cd = 2 if i >= n - 12 else 0
        busy0 = float(i)                           # 0 .. 59
        rows.append(",".join([
            "2026-10-26T08:%02d:%02dZ" % (i // 6, (i % 6) * 10), str(1000 + i * interval), "1.5",
            str(900000 - i * 1000), "1234", str(150000 + i * 100), "2", "2", str(5 + i % 7), "1" if i % 10 == 0 else "0", "3",
            str(18750000 // (n // 1) * 0 + 1875000), "2000000",   # 1.5 Mbit/s rx, 1.6 Mbit/s tx at 10 s
            "%.1f" % busy0, "2.5", "20.0", "0.5",
            "1800000", "2002000", "1500000", "1500000" if i < 50 else "1200000",
            str(soc), str(board), str(cd), str(cd), "4000", "4000",
        ]))
    return rows


class MeasureReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
        self.tmp.write(HEADER + "\n" + "\n".join(synthetic_rows()) + "\n")
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_summary_numbers(self):
        columns, rows = mr.read_rows([self.tmp.name])
        self.assertEqual(len(rows), 60)
        s = mr.summarize(columns, rows)
        self.assertAlmostEqual(s["interval_s"], 10.0)
        self.assertEqual(s["hottest_zone"], "soc_thmzone")
        self.assertAlmostEqual(s["max_temp_c"], 90.0)
        self.assertEqual(s["soc_zone"], "soc_thmzone")
        # samples 20..59 are >= 80 C (40 samples = 6.67 min); samples 25..59 are >= 85 C (35 samples = 5.83 min)
        self.assertAlmostEqual(s["minutes_ge_warm"], 40 * 10 / 60.0)
        self.assertAlmostEqual(s["minutes_ge_hot"], 35 * 10 / 60.0)
        self.assertEqual(s["throttle_samples"], 12)
        self.assertAlmostEqual(s["throttle_minutes"], 2.0)
        self.assertEqual(s["cpu0_busy"]["max"], 59.0)
        self.assertEqual(s["cpu0_busy"]["p50"], 29.0)   # nearest rank of 0..59 at 50 % -> 30th value = 29
        self.assertEqual(s["cpu0_busy"]["p99"], 59.0)
        self.assertAlmostEqual(s["jvm_rss_mb"]["max"], (150000 + 59 * 100) / 1024.0)
        self.assertAlmostEqual(s["wlan0_rx_mbps"]["mean"], 1.5)
        self.assertAlmostEqual(s["wlan0_tx_mbps"]["max"], 1.6)
        self.assertEqual(s["ss_retrans_total"], 6)
        self.assertEqual(s["stations"], {"min": 2.0, "max": 2.0})
        self.assertAlmostEqual(s["policies"]["policy4"]["capped_minutes"], 10 * 10 / 60.0)
        self.assertAlmostEqual(s["irqs"]["53_sprd_pcie"]["per_s_mean"], 400.0)
        self.assertAlmostEqual(s["irqs"]["53_sprd_pcie"]["cpu0_share"], 1.0)

    def test_report_text(self):
        columns, rows = mr.read_rows([self.tmp.name])
        text = mr.format_report(mr.summarize(columns, rows))
        self.assertIn("hottest zone: soc_thmzone  max 90.0 C", text)
        self.assertIn("throttling (cpufreq cooling state > 0): 2.0 min", text)
        self.assertIn("cpu0 busy %: p50 29.0", text)
        self.assertIn("wlan0: rx mean 1.50 Mbit/s", text)

    def test_missing_columns_are_skipped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
            fh.write("time,uptime,load1\n2026-10-26T00:00:00Z,10,0.5\n2026-10-26T00:00:10Z,20,0.7\n")
            name = fh.name
        try:
            columns, rows = mr.read_rows([name])
            s = mr.summarize(columns, rows)
            self.assertEqual(s["samples"], 2)
            self.assertNotIn("cpu0_busy", s)
            self.assertEqual(s["zones"], {})
            text = mr.format_report(s)
            self.assertIn("thermal: no tz_* columns", text)
            self.assertIn("load1 max: 0.70", text)
        finally:
            os.unlink(name)

    def test_empty(self):
        self.assertEqual(mr.format_report(mr.summarize([], [])), "no samples\n")

    def test_percentile(self):
        self.assertEqual(mr.percentile([1, 2, 3, 4], 50), 2)
        self.assertEqual(mr.percentile([1, 2, 3, 4], 100), 4)
        self.assertEqual(mr.percentile([7], 99), 7)
        self.assertIsNone(mr.percentile([], 50))


if __name__ == "__main__":
    unittest.main()
