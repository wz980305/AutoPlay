"""The port the CarPlay viewer (PlayPort's web server) listens on.

18443 unless the owner set one in LuCI (uci viewer_port). An install that only edited
state/receiver/config.json keeps that value too: run-receiver.py used to write 18443 back on every start and
an update's restart dropped the owner's choice (2026-10-23).

The Tesla need not name the port (1.6.8): the box leads port 443 of its own address here, so the address is
https://<name>/ (tesla_openwrt.page_rules). The port itself stays what it was - the owner, 2026-11-18, after a
move to 17989 had been written and not yet released: keep the port, change only what the address bar shows.
"""
import json
from pathlib import Path

DEFAULT = 18443
# LuCI's plain HTTP, the address without a port (led to the viewer, held by uhttpd), and AirPlay.
RESERVED = (80, 443, 7000)


def valid(port):
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    return 1024 <= port <= 65535 and port not in RESERVED


def resolve(state):
    """The receiver's saved httpPort, else 18443."""
    state = Path(state)
    try:
        saved = json.loads((state / "receiver" / "config.json").read_text())
    except (OSError, ValueError):
        saved = {}
    if isinstance(saved, dict) and valid(saved.get("httpPort")):
        return int(saved["httpPort"])
    return DEFAULT
