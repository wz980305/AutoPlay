"""Render the box settings page (settings_page.SettingsPage) in its states as static HTML, for screenshots and eyeballing.

    python3 box/tools/render_settings_states.py <output dir>

Writes box-<state>.html for: fresh (no identity, certificate waiting for a route), live (two phones, one in use),
live-open (a phone's row unfolded), pair-waiting, pair-confirm (passkey), bt-failed, ask-remove and ask-install (the
1.2.0 confirmation screens), and since 1.4.1 checking (a check from the button running in place), invited (an action's
result as the iPhone group's footer) and up-to-date. receiver/web/scripts/ui-shots.mjs photographs them at the Tesla window shapes.
No device, D-Bus or network is touched: the page is given fake status and pairing data.
"""
import json
import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out/ui-states"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "box/scripts/onecloud"))
from settings_page import SettingsPage           # noqa: E402
from status_model import Status                   # noqa: E402
import own_domain                                 # noqa: E402

tmp = tempfile.TemporaryDirectory()
root = Path(tmp.name)
state = root / "state"
(state / "receiver").mkdir(parents=True)
(root / "identity/offline-mfi").mkdir(parents=True)

BASE = dict(mode="openwrt", ssid="AutoPlay-5G", home="http://100.96.0.1:18080/", identity=True,
            entries=["https://car.example.com:18443/", "https://100.96.0.1:18443/"], name="car.example.com",
            own_name="car.example.com", version="1.3.0")
PHONES = {"02:00:00:00:00:01": "小王的 iPhone", "02:00:00:00:00:02": "家人的 iPhone"}
LIVE = {"bluetooth": ("on", None), "identity": ("provided", None), "phone": ("live", None),
        "certificate": ("ok", None, {"not_after": "2027-01-28"}), "uplink": ("online", None)}


def make(fields, devices=None, presence=None, pair=None, cert=None, query="", update_check=None, checking=False):
    status = Status(clock=lambda: 1_793_600_000, **{**BASE, **fields})
    for domain, value in (cert or {}).items():
        status.set(domain, *value[:2], **(value[2] if len(value) > 2 else {}))
    page = SettingsPage(state, status.snapshot, lambda reason: None, lambda: [], root=root)
    page.pairing.devices = lambda: devices or {}
    page.pairing.presence = lambda: presence or {}
    if pair:
        page.pairing.status = lambda: pair
    if checking:
        page.checking.set()
        page.check_started = time.monotonic()
    check = state / "update-check.json"
    if update_check is not None:
        check.write_text(json.dumps(update_check))
    try:
        with patch.object(own_domain, "message", lambda s, n: "正式证书有效期至 2027-01-28。"):
            return page.render(query)
    finally:
        if update_check is not None:
            check.unlink()


def unfold(html, index):
    """Open the index-th <details> of a rendered page (a phone's actions)."""
    at = -1
    for _ in range(index + 1):
        at = html.find("<details>", at + 1)
    return html[:at] + "<details open>" + html[at + len("<details>"):]


states = {
    "fresh": make({"identity": False}, cert={"bluetooth": ("on", None), "identity": ("missing", None),
                                            "certificate": ("issuing", "route")}),
    "live": make({}, devices=PHONES, presence={"active": "02:00:00:00:00:01", "last_phone": "02:00:00:00:00:02"},
                 cert={**LIVE, "update": ("available", None, {"version": "1.4.0"})}),
    "pair-waiting": make({}, pair={"phase": "waiting", "found": [{"address": "02:00:00:00:00:03", "name": "iPhone 15 Pro"}], "error": ""},
                         cert={"bluetooth": ("on", None), "identity": ("provided", None)}),
    "pair-confirm": make({}, pair={"phase": "confirm", "name": "iPhone 15 Pro", "passkey": "482913", "request_id": "r1"},
                         cert={"bluetooth": ("on", None), "identity": ("provided", None)}),
    "bt-failed": make({}, devices={"02:00:00:00:00:01": "小王的 iPhone"},
                      cert={"bluetooth": ("failed", "controller-init-failed", {"retry_in": 60}), "identity": ("provided", None),
                            "certificate": ("expiring_soon", None, {"not_after": "2026-11-20"}), "uplink": ("offline", None)}),
    "ask-remove": make({}, devices=PHONES, presence={"active": "02:00:00:00:00:01"}, cert=LIVE,
                       query="ask=remove&phone=02%3A00%3A00%3A00%3A00%3A02"),
    "ask-install": make({}, devices=PHONES, cert=LIVE, query="ask=install",
                        update_check={"available": True, "online": True, "latest": "1.4.0", "current": "1.3.0",
                                      "checked_at": 1_793_500_000, "notes": "修复若干问题"}),
}
ONE = {"02:00:00:00:00:01": "小王的 iPhone"}
states["checking"] = make({}, devices=ONE, presence={"active": "02:00:00:00:00:01"}, cert=LIVE, checking=True)
states["invited"] = make({}, devices=PHONES, presence={"last_phone": "02:00:00:00:00:02"}, cert=LIVE,
                         query="m=" + "已邀请这部 iPhone 接入，约 1 分钟内有效。请保持它的蓝牙打开。" + "&at=phones",
                         update_check={"available": False, "online": True, "latest": "1.4.1", "current": "1.4.1",
                                       "checked_at": 1_793_500_000})
states["live-open"] = unfold(make({}, devices=PHONES, presence={"active": "02:00:00:00:00:01", "last_phone": "02:00:00:00:00:02"},
                                  cert=LIVE), 1)
for name, html in states.items():
    (OUT / f"box-{name}.html").write_text(html)
    print(f"wrote {OUT / f'box-{name}.html'} ({len(html)} bytes)")
