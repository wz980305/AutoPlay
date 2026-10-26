"""Never trust a clock earlier than the last one seen (reliability_audit #10, platform_audit #11).

The F50 has no battery-backed clock. After a power cut OpenWrt's sysfixtime sets the time to the newest mtime
under /etc, and without a SIM NTP never runs, so the clock can stand still for months or jump backwards. The
Let's Encrypt renewal, the update check's TLS and the log order all read the clock. This is the fake-hwclock
pattern: state/clock-floor holds the latest time the box has seen (written every hour and on NTP/WAN events);
at start the clock is moved forward to it when it is behind. It never moves the clock backwards.

A second time source (the viewer page's Date.now() over the WebSocket, the iPhone's AirPlay time) would need a
channel the receiver does not offer the box today: a receiver-side task (docs/STATUS-MODEL.md).
"""
import os
from pathlib import Path
import time

FILE = "clock-floor"
WRITE_EVERY = 3600
# Before this the box clock is certainly wrong (the tree's own date); never a floor below it.
EARLIEST = 1_760_000_000   # 2025-10-09


def read(state):
    try:
        value = int(float((Path(state) / FILE).read_text().strip()))
    except (OSError, ValueError):
        return None
    return value if value >= EARLIEST else None


def write(state, now=None):
    """Record the current time as the floor (0600, no fsync storm: the file is tiny and rewritten rarely)."""
    now = int(now if now is not None else time.time())
    if now < EARLIEST:
        return False
    path = Path(state) / FILE
    try:
        temporary = path.with_name(path.name + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as out:
            out.write(f"{now}\n")
        temporary.replace(path)
        return True
    except OSError:
        return False


def apply(state, now=None, set_clock=None):
    """At start: move the clock forward to the floor when it is behind. Returns the time set (ISO) or None."""
    floor = read(state)
    current = now if now is not None else time.time()
    if floor is None:
        write(state, current)
        return None
    if current >= floor:
        write(state, current)
        return None
    (set_clock or (lambda t: time.clock_settime(time.CLOCK_REALTIME, t)))(float(floor))
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(floor)) + " UTC"


_last_touch = [0.0]


def touch(state, now=None, every=WRITE_EVERY):
    """Periodic/event update of the floor, rate-limited to one write per `every` seconds."""
    current = now if now is not None else time.time()
    if current - _last_touch[0] < every and _last_touch[0]:
        return False
    if write(state, current):
        _last_touch[0] = current
        return True
    return False
