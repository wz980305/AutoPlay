"""Small durable state files and the fixed addresses of the box.

Extracted from setup_wizard.py (DashPlay) so that the OpenWrt side no longer imports the Debian first-run
wizard for a JSON writer and two constants (code_inventory_trimming.md section 2, hidden couplings).
"""
import ipaddress
import json
import os
from pathlib import Path
import tempfile

MDNS_NAME = "dashplay.local"

# Tesla's browser opens no private address (10/8, 172.16/12, 192.168/16), by name or not, and its Wi-Fi does
# not use IPv6 there; the shared address space 100.64.0.0/10 (RFC 6598) is not private, and a LAN numbered
# 100.96.0.1/24 opens (a friend's F50, 2026-10-14).
SHARED_LAN = ipaddress.IPv4Interface("100.96.0.1/24")
SHARED_SPACE = ipaddress.IPv4Network("100.64.0.0/10")


def tesla_reaches(address):
    """Whether a Tesla's browser opens this box address (not a private one)."""
    try:
        return ipaddress.IPv4Address(address) in SHARED_SPACE
    except ValueError:
        return False


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def save_json(path, value, sync=True):
    """Replace a small state file so that a power cut leaves the old or the new content.
    sync=False for files on tmpfs (RUN): nothing there survives a power cut, and os.sync() flushes every
    filesystem of the box (reliability_audit #11)."""
    path = Path(path)
    # A temporary file of its own per call: two threads saving the same file wrote into one .tmp and the second
    # rename failed (DashPlay review 2026-10-12).
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(value, out)
        out.flush()
        if sync:
            os.fsync(out.fileno())
    Path(temporary).replace(path)
    if sync:
        os.sync()   # the root fs commits only every 120 s; state must survive switching the car off
