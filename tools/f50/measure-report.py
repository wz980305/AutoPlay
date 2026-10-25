#!/usr/bin/env python3
"""Summarise AutoPlay measure.sh CSV files (standard library only).

    python3 tools/f50/measure-report.py measure-*.csv [--hot 85] [--warm 80] [--interval 10]

Prints: time span, hottest zones, minutes at or above the warm/hot thresholds, throttle minutes (any cpufreq cooling
device state > 0), CPU0 busy and softirq percentiles, JVM RSS, memory, Wi-Fi throughput, TCP retransmissions and the
interrupt rates. Columns that are missing from a file are skipped, never invented.
"""
import argparse
import csv
import math
import statistics
import sys


def _num(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except ValueError:
        return None


def percentile(values, pct):
    """Nearest-rank percentile of a non-empty list (pct in 0..100)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int(math.ceil(pct / 100.0 * len(ordered))))
    return ordered[min(rank, len(ordered)) - 1]


def read_rows(paths):
    rows = []
    columns = []
    for path in paths:
        with open(path, newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames:
                for name in reader.fieldnames:
                    if name not in columns:
                        columns.append(name)
            for row in reader:
                if row.get("time", "").startswith("time"):
                    continue  # a header repeated inside a concatenated file
                rows.append(row)
    return columns, rows


def estimate_interval(rows, fallback):
    ups = [_num(r.get("uptime")) for r in rows]
    deltas = [b - a for a, b in zip(ups, ups[1:]) if a is not None and b is not None and 0 < b - a < 3600]
    if len(deltas) < 2:
        return fallback
    return statistics.median(deltas)


def column_values(rows, name):
    return [v for v in (_num(r.get(name)) for r in rows) if v is not None]


def summarize(columns, rows, hot=85.0, warm=80.0, interval=None):
    """Return a dict of computed figures (used by the text report and the tests)."""
    out = {"samples": len(rows)}
    if not rows:
        return out
    interval = interval or estimate_interval(rows, 10.0)
    out["interval_s"] = interval
    out["first_time"] = rows[0].get("time", "")
    out["last_time"] = rows[-1].get("time", "")
    ups = column_values(rows, "uptime")
    if ups:
        out["uptime_first_s"] = ups[0]
        out["uptime_last_s"] = ups[-1]

    # thermal zones
    zones = {}
    for name in columns:
        if name.startswith("tz_") and name.endswith("_mc"):
            vals = column_values(rows, name)
            if vals:
                zones[name[3:-3]] = {"max_c": max(vals) / 1000.0, "mean_c": statistics.fmean(vals) / 1000.0}
    out["zones"] = zones
    if zones:
        hottest = max(zones.items(), key=lambda kv: kv[1]["max_c"])
        out["hottest_zone"] = hottest[0]
        out["max_temp_c"] = hottest[1]["max_c"]
        soc = next((z for z in zones if "soc" in z.lower()), None)
        out["soc_zone"] = soc
        # minutes above thresholds, judged on the SoC zone when present, else on the per-sample maximum of all zones
        per_sample = []
        for r in rows:
            if soc:
                v = _num(r.get("tz_%s_mc" % soc))
                per_sample.append(v / 1000.0 if v is not None else None)
            else:
                vs = [_num(r.get("tz_%s_mc" % z)) for z in zones]
                vs = [v for v in vs if v is not None]
                per_sample.append(max(vs) / 1000.0 if vs else None)
        out["minutes_ge_warm"] = sum(1 for v in per_sample if v is not None and v >= warm) * interval / 60.0
        out["minutes_ge_hot"] = sum(1 for v in per_sample if v is not None and v >= hot) * interval / 60.0

    # throttling: any cpufreq cooling device with cur_state > 0
    cdev_cols = [c for c in columns if c.startswith("cd") and "cpufreq" in c.lower()]
    out["throttle_columns"] = cdev_cols
    if cdev_cols:
        throttled = 0
        for r in rows:
            if any((_num(r.get(c)) or 0) > 0 for c in cdev_cols):
                throttled += 1
        out["throttle_samples"] = throttled
        out["throttle_minutes"] = throttled * interval / 60.0

    # cpufreq policies: mean and min of scaling_cur_freq, and how often scaling_max_freq sat below its own maximum
    policies = {}
    for name in columns:
        if name.startswith("policy") and name.endswith("_cur_khz"):
            pname = name[: -len("_cur_khz")]
            cur = column_values(rows, name)
            mx = column_values(rows, pname + "_max_khz")
            if cur:
                policies[pname] = {"cur_mean_mhz": statistics.fmean(cur) / 1000.0, "cur_min_mhz": min(cur) / 1000.0}
                if mx:
                    top = max(mx)
                    policies[pname]["max_khz_top"] = top
                    policies[pname]["capped_minutes"] = sum(1 for v in mx if v < top) * interval / 60.0
    out["policies"] = policies

    # CPU0 (where the Wi-Fi/BT/modem interrupts land)
    busy0 = column_values(rows, "cpu0_busy")
    if busy0:
        out["cpu0_busy"] = {"p50": percentile(busy0, 50), "p90": percentile(busy0, 90), "p99": percentile(busy0, 99), "max": max(busy0)}
    si0 = column_values(rows, "cpu0_softirq")
    if si0:
        out["cpu0_softirq"] = {"p50": percentile(si0, 50), "p99": percentile(si0, 99), "max": max(si0)}
    all_busy = []
    for name in columns:
        if name.startswith("cpu") and name.endswith("_busy"):
            vals = column_values(rows, name)
            if vals:
                all_busy.append((name, statistics.fmean(vals)))
    out["cpu_mean_busy"] = all_busy

    # memory and JVM
    rss = column_values(rows, "jvm_rss_kb")
    if rss:
        out["jvm_rss_mb"] = {"max": max(rss) / 1024.0, "mean": statistics.fmean(rss) / 1024.0}
    mem = column_values(rows, "mem_avail_kb")
    if mem:
        out["mem_avail_mb_min"] = min(mem) / 1024.0
    load = column_values(rows, "load1")
    if load:
        out["load1_max"] = max(load)

    # Wi-Fi
    rx = column_values(rows, "wlan0_rx_bytes_d")
    tx = column_values(rows, "wlan0_tx_bytes_d")
    if rx and interval:
        out["wlan0_rx_mbps"] = {"mean": statistics.fmean(rx) * 8 / interval / 1e6, "max": max(rx) * 8 / interval / 1e6}
    if tx and interval:
        out["wlan0_tx_mbps"] = {"mean": statistics.fmean(tx) * 8 / interval / 1e6, "max": max(tx) * 8 / interval / 1e6}
    st = column_values(rows, "stations")
    if st:
        out["stations"] = {"min": min(st), "max": max(st)}
    rtt = column_values(rows, "ss_rtt_max_ms")
    if rtt:
        out["ss_rtt_ms"] = {"p50": percentile(rtt, 50), "max": max(rtt)}
    retr = column_values(rows, "ss_retrans_d")
    if retr:
        out["ss_retrans_total"] = sum(v for v in retr if v > 0)
    unack = column_values(rows, "ss_unacked_max")
    if unack:
        out["ss_unacked_max"] = max(unack)

    # interrupts
    irqs = {}
    for name in columns:
        if name.startswith("irq") and name.endswith("_d") and not name.endswith("_cpu0_d"):
            tot = column_values(rows, name)
            cpu0 = column_values(rows, name[:-2] + "_cpu0_d")
            if tot and interval:
                entry = {"per_s_mean": statistics.fmean(tot) / interval, "per_s_max": max(tot) / interval}
                if cpu0 and sum(tot) > 0:
                    entry["cpu0_share"] = sum(cpu0) / sum(tot)
                irqs[name[3:-2]] = entry
    out["irqs"] = irqs
    return out


def format_report(s, hot=85.0, warm=80.0):
    lines = []
    if not s.get("samples"):
        return "no samples\n"
    lines.append("AutoPlay measurement summary")
    lines.append("  samples: %d  interval: %.1f s  span: %s .. %s" % (s["samples"], s.get("interval_s", 0), s.get("first_time", "?"), s.get("last_time", "?")))
    if "uptime_first_s" in s:
        lines.append("  uptime: %.0f s .. %.0f s (%.1f min logged)" % (s["uptime_first_s"], s["uptime_last_s"], (s["uptime_last_s"] - s["uptime_first_s"]) / 60.0))
    zones = s.get("zones") or {}
    if zones:
        lines.append("thermal")
        lines.append("  hottest zone: %s  max %.1f C" % (s["hottest_zone"], s["max_temp_c"]))
        basis = s.get("soc_zone") or "max of all zones"
        lines.append("  minutes >= %.0f C: %.1f   minutes >= %.0f C: %.1f   (basis: %s)" % (warm, s["minutes_ge_warm"], hot, s["minutes_ge_hot"], basis))
        top = sorted(zones.items(), key=lambda kv: -kv[1]["max_c"])[:8]
        for name, z in top:
            lines.append("    %-28s max %6.1f C  mean %6.1f C" % (name, z["max_c"], z["mean_c"]))
    else:
        lines.append("thermal: no tz_* columns")
    if s.get("throttle_columns"):
        lines.append("throttling (cpufreq cooling state > 0): %.1f min in %d samples  [%s]" % (s.get("throttle_minutes", 0), s.get("throttle_samples", 0), ", ".join(s["throttle_columns"])))
    else:
        lines.append("throttling: no cpufreq cooling-device columns")
    pol = s.get("policies") or {}
    for name, p in sorted(pol.items()):
        extra = ""
        if "capped_minutes" in p:
            extra = "  scaling_max below %.0f MHz for %.1f min" % (p["max_khz_top"] / 1000.0, p["capped_minutes"])
        lines.append("  %-8s cur mean %7.0f MHz  min %7.0f MHz%s" % (name, p["cur_mean_mhz"], p["cur_min_mhz"], extra))
    if "cpu0_busy" in s:
        b = s["cpu0_busy"]
        lines.append("cpu0 busy %%: p50 %.1f  p90 %.1f  p99 %.1f  max %.1f" % (b["p50"], b["p90"], b["p99"], b["max"]))
    if "cpu0_softirq" in s:
        b = s["cpu0_softirq"]
        lines.append("cpu0 softirq %%: p50 %.1f  p99 %.1f  max %.1f" % (b["p50"], b["p99"], b["max"]))
    if s.get("cpu_mean_busy"):
        lines.append("  mean busy per cpu: " + "  ".join("%s %.1f" % (n.replace("_busy", ""), v) for n, v in s["cpu_mean_busy"]))
    if "jvm_rss_mb" in s:
        lines.append("jvm rss: max %.0f MB  mean %.0f MB" % (s["jvm_rss_mb"]["max"], s["jvm_rss_mb"]["mean"]))
    if "mem_avail_mb_min" in s:
        lines.append("MemAvailable min: %.0f MB" % s["mem_avail_mb_min"])
    if "load1_max" in s:
        lines.append("load1 max: %.2f" % s["load1_max"])
    if "wlan0_rx_mbps" in s or "wlan0_tx_mbps" in s:
        rx = s.get("wlan0_rx_mbps", {"mean": 0, "max": 0})
        tx = s.get("wlan0_tx_mbps", {"mean": 0, "max": 0})
        lines.append("wlan0: rx mean %.2f Mbit/s max %.2f   tx mean %.2f Mbit/s max %.2f" % (rx["mean"], rx["max"], tx["mean"], tx["max"]))
    if "stations" in s:
        lines.append("stations: min %d  max %d" % (s["stations"]["min"], s["stations"]["max"]))
    if "ss_rtt_ms" in s:
        lines.append("tcp to car: rtt p50 %.1f ms  max %.1f ms  retrans total %d  unacked max %d" % (
            s["ss_rtt_ms"]["p50"], s["ss_rtt_ms"]["max"], s.get("ss_retrans_total", 0), s.get("ss_unacked_max", 0)))
    irqs = s.get("irqs") or {}
    if irqs:
        lines.append("interrupts (per second)")
        for name, e in sorted(irqs.items(), key=lambda kv: -kv[1]["per_s_mean"]):
            share = ("  cpu0 share %.0f%%" % (100 * e["cpu0_share"])) if "cpu0_share" in e else ""
            lines.append("  %-32s mean %8.1f  max %8.1f%s" % (name, e["per_s_mean"], e["per_s_max"], share))
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--hot", type=float, default=85.0, help="hot threshold in C (default 85, the IPA control point)")
    ap.add_argument("--warm", type=float, default=80.0, help="warm threshold in C (default 80, the viewer's planned fallback point)")
    ap.add_argument("--interval", type=float, default=None, help="sample interval in s (default: from the uptime column)")
    args = ap.parse_args(argv)
    columns, rows = read_rows(args.files)
    summary = summarize(columns, rows, hot=args.hot, warm=args.warm, interval=args.interval)
    sys.stdout.write(format_report(summary, hot=args.hot, warm=args.warm))
    return 0


if __name__ == "__main__":
    sys.exit(main())
