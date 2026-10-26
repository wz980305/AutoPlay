"""Per-component supervision (reliability_audit #1, #2, #4, #5): back-off, restart budgets, liveness strikes,
Wi-Fi misses, the Bluetooth and receiver managers driven with a fake clock and fake children."""
import ipaddress
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
import supervision
import supervisor_openwrt as sup
from status_model import Status


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class BackoffTests(unittest.TestCase):
    def test_exponential_with_cap(self):
        self.assertEqual([supervision.backoff(n, 1, 60) for n in range(8)], [1, 2, 4, 8, 16, 32, 60, 60])
        self.assertEqual([supervision.backoff(n, 10, 60) for n in range(4)], [10, 20, 40, 60])

    def test_bluetooth_schedule_is_10_20_40_then_60(self):
        clock = FakeClock()
        schedule = supervision.Schedule(clock=clock)
        self.assertTrue(schedule.due())
        delays = []
        for _ in range(6):
            delays.append(schedule.failed())
            self.assertFalse(schedule.due())
            clock.advance(delays[-1])
            self.assertTrue(schedule.due())
        self.assertEqual(delays, [10, 20, 40, 60, 60, 60])
        schedule.reset()
        self.assertEqual(schedule.failed(), 10)


class RestarterTests(unittest.TestCase):
    def test_backoff_grows_and_degrades_after_five_failures_in_the_window(self):
        clock = FakeClock()
        restarter = supervision.Restarter("receiver", first=2.0, cap=60.0, degraded_after=5, clock=clock)
        delays = []
        for n in range(6):
            restarter.started()
            clock.advance(1)
            delays.append(restarter.failed(f"exit-{n}"))
            self.assertFalse(restarter.ready())
            clock.advance(delays[-1])
            self.assertTrue(restarter.ready())
        self.assertEqual(delays, [2, 4, 8, 16, 32, 60])
        self.assertTrue(restarter.degraded)
        self.assertEqual(restarter.reason, "exit-5")

    def test_a_long_healthy_run_forgives_the_past(self):
        clock = FakeClock()
        restarter = supervision.Restarter("receiver", first=2.0, cap=60.0, degraded_after=5, clock=clock)
        for _ in range(5):
            restarter.started(); clock.advance(1); restarter.failed("x"); clock.advance(60)
        self.assertTrue(restarter.degraded)
        restarter.started()
        clock.advance(601)
        restarter.recovered()
        self.assertFalse(restarter.degraded)
        self.assertEqual(restarter.failed("y"), 2.0, "the count starts over")

    def test_not_waiting_before_the_first_failure(self):
        restarter = supervision.Restarter("x", clock=FakeClock())
        self.assertFalse(restarter.waiting())
        self.assertFalse(restarter.ready())


class LivenessTests(unittest.TestCase):
    def test_three_strikes(self):
        clock = FakeClock()
        liveness = supervision.Liveness(limit=3, every=10, clock=clock)
        self.assertFalse(liveness.due())
        clock.advance(10)
        self.assertTrue(liveness.due())
        self.assertFalse(liveness.record(False))
        self.assertFalse(liveness.record(False))
        self.assertFalse(liveness.record(True), "a hit resets the count")
        self.assertFalse(liveness.record(False))
        self.assertFalse(liveness.record(False))
        self.assertTrue(liveness.record(False))
        self.assertEqual(liveness.strikes, 0)

    def test_grace_after_a_start(self):
        clock = FakeClock()
        liveness = supervision.Liveness(limit=3, every=10, clock=clock)
        liveness.reset(grace=90)
        clock.advance(60)
        self.assertFalse(liveness.due())
        clock.advance(31)
        self.assertTrue(liveness.due())


class MissesAndGuardTests(unittest.TestCase):
    def test_wifi_missing_counts_only_after_three_misses(self):
        misses = supervision.Misses(limit=3)
        self.assertFalse(misses.miss()); self.assertFalse(misses.miss())
        misses.hit()
        self.assertFalse(misses.miss()); self.assertFalse(misses.miss()); self.assertTrue(misses.miss())

    def test_guard_logs_counts_and_never_raises(self):
        said = []
        guard = supervision.Guard("check", said.append)
        def boom():
            raise OSError("ubus hung")
        for _ in range(4):
            self.assertIsNone(guard(boom))
        self.assertEqual(guard.failures, 4)
        self.assertEqual(len(said), 2, "said at 1 and 3, not every time")
        self.assertEqual(guard(lambda: 42), 42)
        self.assertEqual(guard.failures, 0)
        self.assertIn("recovered", said[-1])


class FakeChild:
    def __init__(self, code=None):
        self.returncode = code
        self.pid = 4242

    def poll(self):
        return self.returncode


class FakePlatform:
    def __init__(self):
        self.children = []
        self.started = []
        self.stopped = []
        self.run = Path("/nonexistent")
        self.power_results = []

    def start(self, name, argv):
        child = FakeChild()
        self.children.append((name, child))
        self.started.append((name, argv))
        return child

    def child(self, name):
        return next((c for n, c in self.children if n == name), None)

    def stop_child(self, name, timeout=8):
        self.stopped.append(name)
        self.children = [(n, c) for n, c in self.children if n != name]

    def forget_child(self, name):
        self.children = [(n, c) for n, c in self.children if n != name]

    def power_bluetooth(self):
        return self.power_results.pop(0) if self.power_results else False


def wait_threads(manager, attribute):
    for _ in range(100):
        pending = getattr(manager, attribute)
        if pending is None or not pending[0].is_alive():
            return
        time.sleep(0.01)


class BluetoothManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.clock = FakeClock()
        self.platform = FakePlatform()
        self.status = Status(clock=lambda: 1_700_000_000)
        self.said = []
        self.hci = Path(self.tmp.name) / "hci0"
        self.manager = sup.BluetoothManager(self.platform, Path("/opt/dashplay"), Path(self.tmp.name), self.status,
                                            self.said.append, clock=self.clock, hci=self.hci)

    def power_cycle(self, result):
        """One tick that runs a power attempt (in its thread) and the tick that reads it."""
        self.platform.power_results.append(result)
        self.manager.tick()
        wait_threads(self.manager, "attempt")
        self.manager.tick()

    def test_retries_power_in_the_background_with_backoff_and_reports(self):
        self.manager.start()
        self.assertEqual(self.platform.started[0][0], "bluetooth")
        self.assertEqual(self.status.state("bluetooth"), "starting")
        for expected in (10, 20, 40):
            self.power_cycle(False)
            self.assertFalse(self.manager.powered)
            self.assertEqual(self.status.domain("bluetooth")["retry_in"], expected)
            self.assertEqual(self.status.state("bluetooth"), "starting")
            self.manager.tick()   # not due yet: no new attempt
            self.assertIsNone(self.manager.attempt)
            self.clock.advance(expected)
        self.power_cycle(False)   # the fourth miss: 60 s and a visible failure, still retrying
        self.assertEqual(self.status.state("bluetooth"), "failed")
        self.assertEqual(self.status.domain("bluetooth")["reason"], "adapter-not-powered")
        self.assertEqual(self.status.domain("bluetooth")["retry_in"], 60)
        self.clock.advance(60)
        powered = []
        self.manager.on_powered = lambda: powered.append(True)
        self.hci.mkdir()
        self.power_cycle(True)
        self.assertTrue(self.manager.powered)
        self.assertEqual(self.status.state("bluetooth"), "on")
        self.assertEqual(powered, [True], "the receiver is relaunched with wireless")

    def test_helper_exit_restarts_only_the_helper_with_a_reason(self):
        (Path(self.tmp.name) / "bluetooth.log").write_text("F50 Bluetooth ready\nbtattach exited with 1\n")
        self.platform.run = Path(self.tmp.name)
        self.manager.start()
        self.platform.child("bluetooth").returncode = 1
        self.manager.tick()
        self.assertEqual(self.status.state("bluetooth"), "failed")
        self.assertEqual(self.status.domain("bluetooth")["reason"], "daemon-exit")
        self.assertIsNone(self.platform.child("bluetooth"))
        self.manager.tick()
        self.assertEqual(len(self.platform.started), 1, "waits for the back-off")
        self.clock.advance(5)
        self.manager.tick()
        self.assertEqual(len(self.platform.started), 2)
        self.assertEqual(self.status.state("bluetooth"), "starting")

    def test_five_helper_exits_mark_degraded_but_keep_trying(self):
        self.platform.run = Path(self.tmp.name)
        (Path(self.tmp.name) / "bluetooth.log").write_text("Marlin3 Bluetooth init failed\n")
        self.manager.start()
        for n in range(5):
            self.platform.child("bluetooth").returncode = 1
            self.manager.tick()
            self.assertEqual(self.status.domain("bluetooth")["reason"], "controller-init-failed")
            self.assertEqual(self.status.domain("bluetooth")["degraded"], n == 4)
            self.clock.advance(61)
            self.manager.tick()
        self.assertTrue(self.manager.restarter.degraded)
        self.assertEqual(len(self.platform.started), 6, "degraded still retries, at the cap")

    def test_a_vanished_hci0_restarts_the_helper(self):
        self.manager.start()
        self.hci.mkdir()
        self.power_cycle(True)
        self.assertTrue(self.manager.powered)
        self.hci.rmdir()
        self.manager.tick()
        self.assertFalse(self.manager.powered)
        self.assertEqual(self.platform.stopped, ["bluetooth"])
        self.assertEqual(self.status.domain("bluetooth")["reason"], "hci-lost")


class ReceiverManagerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.platform = FakePlatform()
        self.status = Status(clock=lambda: 1_700_000_000)
        self.said = []
        self.probe_results = []
        self.network = {"ssid": "Car-5G", "key": "k", "security": "wpa2", "channel": 149, "device": "br-lan",
                        "address": ipaddress.IPv4Interface("100.96.0.1/24")}
        self.manager = sup.ReceiverManager(self.platform, self.status, self.said.append, 18443,
                                           lambda network, wireless, wait: ["run", "wireless" if wireless else "no-wireless"],
                                           clock=self.clock, probe=lambda: self.probe_results.pop(0))

    def probe_cycle(self, alive):
        self.probe_results.append(alive)
        self.manager.tick()
        wait_threads(self.manager, "probing")
        self.manager.tick()

    def test_an_exit_restarts_only_the_receiver_with_backoff(self):
        self.manager.launch(self.network, True)
        self.assertEqual(self.status.state("system"), "starting")
        self.platform.child("receiver").returncode = 1
        self.manager.tick()
        self.assertEqual(self.status.state("system"), "restarting")
        self.assertEqual(self.status.domain("system")["reason"], "receiver-exit-1")
        self.manager.tick()
        self.assertEqual(len(self.platform.started), 1)
        self.clock.advance(2)
        self.manager.tick()
        self.assertEqual(len(self.platform.started), 2)
        self.assertEqual(self.platform.started[1][1], ["run", "wireless"])

    def test_three_missed_probes_restart_a_wedged_jvm(self):
        self.manager.launch(self.network, True)
        self.clock.advance(91)
        self.probe_cycle(True)
        self.assertEqual(self.status.state("system"), "ok")
        for _ in range(2):
            self.clock.advance(10)
            self.probe_cycle(False)
            self.assertEqual(len(self.platform.stopped), 0)
        self.clock.advance(10)
        self.probe_cycle(False)
        self.assertEqual(self.platform.stopped, ["receiver"])
        self.assertEqual(self.status.domain("system")["reason"], "receiver-liveness")
        self.clock.advance(2)
        self.manager.tick()
        self.assertEqual(len(self.platform.started), 2)

    def test_relaunch_with_wireless_once_bluetooth_is_up(self):
        self.manager.launch(self.network, False)
        self.assertEqual(self.platform.started[0][1], ["run", "no-wireless"])
        self.manager.relaunch(wireless=True, why="Bluetooth came up")
        self.assertEqual(self.platform.stopped, ["receiver"])
        self.assertEqual(self.platform.started[1][1], ["run", "wireless"])
        self.assertTrue(self.manager.wireless)

    def test_degraded_after_five_exits_keeps_restarting_at_the_cap(self):
        self.manager.launch(self.network, True)
        for n in range(6):
            self.platform.child("receiver").returncode = 70
            self.manager.tick()
            self.assertEqual(self.status.state("system"), "degraded" if n >= 4 else "restarting")
            self.clock.advance(61)
            self.manager.tick()
        self.assertTrue(self.manager.restarter.degraded)
        self.assertEqual(len(self.platform.started), 7, "degraded still retries, at the cap")


class ReasonTests(unittest.TestCase):
    def test_helper_reason_words(self):
        self.assertEqual(sup.helper_reason("x\nMarlin3 Bluetooth init failed\n", 1), "controller-init-failed")
        self.assertEqual(sup.helper_reason("missing /opt/dashplay-bluez/usr/bin/bluetoothd: run board_zte_f50.py --setup", 1), "bluez-missing")
        self.assertEqual(sup.helper_reason("Bluetooth controller did not come up"), "controller-timeout")
        self.assertEqual(sup.helper_reason("", 137), "helper-exit-137")

    def test_bridge_reasons_and_pairing_lost(self):
        log = ("bt-bridge: RFCOMM connected\nbt-bridge: ConnectProfile: br-connection-key-missing\nbt-bridge: reason=pairing-lost\n"
               "bt-bridge: reason=page-timeout\nbt-bridge: reason=auth-failed\nbt-bridge: reason=pairing-lost\n")
        reasons = sup.bridge_reasons(log)
        self.assertEqual(reasons, ["pairing-lost", "page-timeout", "auth-failed", "pairing-lost"])
        self.assertTrue(sup.pairing_lost(reasons))
        self.assertFalse(sup.pairing_lost(["pairing-lost", "page-timeout"]))
        self.assertFalse(sup.pairing_lost(["pairing-lost"]))
        self.assertEqual(sup.phone_state({"active": "AA"}, reasons=reasons), ("live", None))
        self.assertEqual(sup.phone_state({}, reasons=reasons), ("pairing-lost", "pairing-lost"))
        self.assertEqual(sup.phone_state({}, reasons=["page-timeout"]), ("idle", "page-timeout"))
        self.assertEqual(sup.phone_state({"declined": {"AA": 1}}), ("declined", None))
        self.assertEqual(sup.phone_state({}), ("idle", None))

    def test_channel_warning(self):
        self.assertEqual(sup.channel_warning(149), "")
        self.assertEqual(sup.channel_warning(36), "")
        self.assertIn("52", sup.channel_warning(52))
        self.assertIn("2.4 GHz", sup.channel_warning(6))
        self.assertEqual(sup.channel_warning(None), "")

    def test_no_station_is_ever_deauthenticated(self):
        # reliability_audit #3: a dnsmasq restart must never cost the iPhone its Wi-Fi.
        scripts = Path(__file__).resolve().parents[2] / "scripts/onecloud"
        for path in scripts.glob("*.py"):
            text = path.read_text()
            self.assertNotIn("del_client", text, path.name)
            self.assertNotIn('"deauth"', text, path.name)


if __name__ == "__main__":
    unittest.main()
