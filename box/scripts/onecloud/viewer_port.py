"""The port the CarPlay viewer (PlayPort's web server) listens on.

17989 unless the owner set one in LuCI (uci viewer_port). An install that only edited
state/receiver/config.json keeps that value too: run-receiver.py used to write the default back on every start and
an update's restart dropped the owner's choice (2026-10-23).

Until 1.6.7 the default was 18443 (the owner, 2026-11-16: 17989, and the address without any port where that can
be done). A box that still carries 18443 moves to 17989 once, see choose(); the box goes on answering on 18443
and answers on 443 too, so the Tesla opens https://<name>/ (tesla_openwrt.redirect_rules).
"""
import json
from pathlib import Path

DEFAULT = 17989
# The default until 1.6.7: moved to DEFAULT once, and redirected to the viewer for as long as the box runs, so a
# bookmark or an open page on the old address keeps working.
LEGACY = 18443
# state/: the move was made, or was not needed. From then on 18443 in the uci is the owner's own choice.
MOVED = "viewer-port-moved"
# The box settings page's plain HTTP, the address without a port (redirected to the viewer), and AirPlay.
RESERVED = (80, 443, 7000)


def valid(port):
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    return 1024 <= port <= 65535 and port not in RESERVED


def resolve(state):
    """The receiver's saved httpPort, else 17989."""
    state = Path(state)
    try:
        saved = json.loads((state / "receiver" / "config.json").read_text())
    except (OSError, ValueError):
        saved = {}
    if isinstance(saved, dict) and valid(saved.get("httpPort")):
        return int(saved["httpPort"])
    return DEFAULT


def choose(configured, state, hold=False):
    """(port, settle): the port to listen on, and whether settle() is due.

    configured is the uci value ('' when unset; the supervisor mirrors the port in use into it, so an installed box
    carries a number). A box that carries the old default moves to the new one, once. hold: this start is the one an
    online update is checking (update.py's journal says "installing"); the port stays as it is, because a version
    that fails the check is replaced by the previous one, which reads the same uci and has no redirect from 18443 -
    the car's bookmark would then lead nowhere. The move is made at the next start instead."""
    port = int(configured) if str(configured or "").isdigit() else resolve(state)
    if hold or (Path(state) / MOVED).exists():
        return port, False
    return (DEFAULT if port == LEGACY else port), True


def settle(state):
    """Remember that choose() has made its one move."""
    try:
        (Path(state) / MOVED).write_text("1\n")
    except OSError:
        pass   # asked again at the next start; a box already on 17989 is left there
