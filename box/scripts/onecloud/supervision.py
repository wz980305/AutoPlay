"""Per-component supervision: back-off, restart budgets, liveness strikes and guarded periodic work.

Pure state machines driven by a clock, so the supervisor's policy can be tested without processes
(reliability_audit #1, #2, #4, #5). The supervisor (supervisor_openwrt.py) owns the processes and asks these
classes what to do next.
"""
import time


def backoff(attempt, first=1.0, cap=60.0):
    """Exponential back-off: first, 2*first, 4*first ... capped. attempt 0 is the first retry."""
    return min(cap, first * (2 ** max(0, attempt)))


class Restarter:
    """When a child exits: how long to wait before starting it again, and when to give up on it.

    Failures are counted inside a sliding window; after `degraded_after` of them the component is degraded
    (the supervisor keeps the rest running and shows the reason), and the back-off stays at the cap. A child
    that then runs for `stable_after` seconds resets the count."""

    def __init__(self, name, first=1.0, cap=60.0, degraded_after=5, window=600.0, stable_after=600.0,
                 clock=time.monotonic):
        self.name, self.first, self.cap = name, first, cap
        self.degraded_after, self.window, self.stable_after = degraded_after, window, stable_after
        self.clock = clock
        self.failures = []          # monotonic times of the failures inside the window
        self.started_at = None
        self.due = None             # when the next start may happen (None: not waiting)
        self.reason = None          # the last failure's reason code
        self.degraded = False

    def started(self):
        self.started_at = self.clock()
        self.due = None

    def failed(self, reason):
        """The child exited (or was found dead). Returns the delay before the next start."""
        now = self.clock()
        if self.started_at is not None and now - self.started_at >= self.stable_after:
            self.failures = []   # a long healthy run forgives the past
        self.failures = [at for at in self.failures if now - at <= self.window] + [now]
        self.reason = reason
        self.started_at = None
        attempt = len(self.failures) - 1
        delay = backoff(attempt, self.first, self.cap)
        self.degraded = len(self.failures) >= self.degraded_after
        self.due = now + delay
        return delay

    def ready(self):
        """The back-off has passed: start the child again."""
        return self.due is not None and self.clock() >= self.due

    def waiting(self):
        return self.due is not None

    def recovered(self):
        """Call when the child has proved itself (e.g. a liveness hit after a restart)."""
        if self.started_at is not None and self.clock() - self.started_at >= self.stable_after:
            self.failures, self.degraded, self.reason = [], False, None


class Liveness:
    """Three strikes: a probe that fails `limit` times in a row means the component is dead even if its process
    is still there (a wedged JVM, reliability_audit #5)."""

    def __init__(self, limit=3, every=10.0, clock=time.monotonic):
        self.limit, self.every, self.clock = limit, every, clock
        self.strikes = 0
        self.next_at = clock() + every

    def due(self):
        return self.clock() >= self.next_at

    def record(self, alive):
        """Returns True when the strike limit is reached (and resets the count)."""
        self.next_at = self.clock() + self.every
        if alive:
            self.strikes = 0
            return False
        self.strikes += 1
        if self.strikes >= self.limit:
            self.strikes = 0
            return True
        return False

    def reset(self, grace=0.0):
        """After a (re)start: no probe before `grace` seconds have passed."""
        self.strikes = 0
        self.next_at = self.clock() + max(self.every, grace)


class Misses:
    """Act on an absence only after N consecutive misses (a ubus stall must not restart the service,
    reliability_audit #4)."""

    def __init__(self, limit=3):
        self.limit, self.count = limit, 0

    def miss(self):
        self.count += 1
        return self.count >= self.limit

    def hit(self):
        self.count = 0


class Guard:
    """Run a periodic check without letting its failure end the service; count consecutive failures."""

    def __init__(self, name, say=print):
        self.name, self.say = name, say
        self.failures = 0
        self.last_error = None

    def __call__(self, function, *args, **kwargs):
        try:
            result = function(*args, **kwargs)
        except Exception as error:   # noqa: BLE001 - any failure of a periodic check is logged and counted
            self.failures += 1
            text = f"{type(error).__name__}: {error}"
            if text != self.last_error or self.failures in (1, 3, 10, 30, 100):
                self.say(f"{self.name} failed ({self.failures} in a row): {text}")
            self.last_error = text
            return None
        if self.failures:
            self.say(f"{self.name} recovered after {self.failures} failures")
        self.failures, self.last_error = 0, None
        return result


class Schedule:
    """Retry schedule for a bring-up that may take several tries (Bluetooth: 10, 20, 40, 60, 60 ... s)."""

    def __init__(self, delays=(10, 20, 40), cap=60, clock=time.monotonic):
        self.delays, self.cap, self.clock = tuple(delays), cap, clock
        self.attempt = 0
        self.next_at = clock()

    def due(self):
        return self.clock() >= self.next_at

    def failed(self):
        """Returns the delay before the next try."""
        delay = self.delays[self.attempt] if self.attempt < len(self.delays) else self.cap
        self.attempt += 1
        self.next_at = self.clock() + delay
        return delay

    def reset(self):
        self.attempt = 0
        self.next_at = self.clock()
