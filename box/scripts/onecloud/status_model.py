"""The box's status in one place, with reason codes (settings_onboarding_audit S2/S7/S13, reliability_audit #13).

Nine domains, each {state, reason, since}: bluetooth, wifi, uplink, identity, phone, certificate, update, system,
tesla (docs/STATUS-MODEL.md lists the states). `since` is the wall-clock time the state last changed, so a
page can mark a stale entry. The flat keys the settings page and the receiver used from DashPlay (mode, ssid,
home, entries, warning, ...) stay beside them. The snapshot is written to RUN/status.json on change only
(tmpfs, no fsync): the settings page serves it, LuCI and the receiver may read it.
"""
import json
from pathlib import Path
import threading
import time

import state as state_files

DOMAINS = ("bluetooth", "wifi", "uplink", "identity", "phone", "certificate", "update", "system", "tesla")


class Status:
    def __init__(self, path=None, clock=time.time, **flat):
        self.path = Path(path) if path else None
        self.clock = clock
        self.flat = dict(flat)
        self.domains = {name: {"state": "unknown", "reason": None, "since": round(clock())} for name in DOMAINS}
        self.lock = threading.Lock()
        self.written = None

    # Domains ---------------------------------------------------------------------------------

    def set(self, domain, state, reason=None, **extra):
        """Record a domain's state; `since` moves only when the state or the reason changes. Returns True then."""
        if domain not in self.domains:
            raise KeyError(domain)
        with self.lock:
            entry = self.domains[domain]
            state_changed = entry["state"] != state or entry.get("reason") != reason
            replacement = {"state": state, "reason": reason,
                           "since": round(self.clock()) if state_changed else entry["since"], **extra}
            changed = entry != replacement
            if changed:
                self.domains[domain] = replacement
        if changed:
            self.write()
        return changed

    def domain(self, name):
        with self.lock:
            return dict(self.domains[name])

    def state(self, domain):
        with self.lock:
            return self.domains[domain]["state"]

    # Flat keys (the settings page's needs) --------------------------------------------------

    def update(self, **flat):
        with self.lock:
            changed = any(self.flat.get(key) != value for key, value in flat.items())
            self.flat.update(flat)
        if changed:
            self.write()

    def pop(self, key, default=None):
        with self.lock:
            had = key in self.flat
            value = self.flat.pop(key, default)
        if had:
            self.write()
        return value

    def get(self, key, default=None):
        return self.flat.get(key, default)

    def __getitem__(self, key):
        return self.flat[key]

    def __setitem__(self, key, value):
        self.update(**{key: value})

    def __contains__(self, key):
        return key in self.flat

    # Snapshot --------------------------------------------------------------------------------

    def snapshot(self):
        """Everything the page shows, as one dict: the flat keys plus one entry per domain."""
        with self.lock:
            data = dict(self.flat)
            data.update({name: dict(entry) for name, entry in self.domains.items()})
        data["updated"] = round(self.clock())
        return data

    def write(self):
        """RUN/status.json, on change only; a page polling it sees `updated` move with every write."""
        if self.path is None:
            return
        with self.lock:
            body = {**dict(self.flat), **{name: dict(entry) for name, entry in self.domains.items()}}
            text = json.dumps(body, sort_keys=True, ensure_ascii=False)
            if text == self.written:
                return
            body["updated"] = round(self.clock())
            # Keep commits ordered across the diagnostics and supervisor threads. Publishing outside
            # this lock lets an older snapshot overwrite a newer one. Failed writes must remain retryable.
            try:
                state_files.save_json(self.path, body, sync=False)
            except OSError:
                return
            self.written = text


def read(path):
    """A status snapshot written by the supervisor, or {} (for update.py's health check and the viewer)."""
    value = state_files.load_json(path, {})
    return value if isinstance(value, dict) else {}
