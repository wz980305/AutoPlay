"""One word for why an invitation failed, for the receiver log and the status page.

The bridge prints `bt-bridge: reason=<word>` to stderr when it fails; the supervisor reads those lines from the
receiver log (supervisor_openwrt.bridge_reasons) and the settings page turns two consecutive authentication
failures into "delete this iPhone and add it again". Re-implemented from the dashplay-tesla fork's design
(borrowability.md 2b.11, 2j); no code copied. Pure: importable without dbus-next, so it is unit-tested where the
D-Bus tests cannot run.
"""
import re

WORDS = ("pairing-lost", "page-timeout", "busy", "aborted", "timeout", "auth-failed", "not-paired", "powered-off",
         "blocked", "no-adapter", "bluez-gone", "refused", "unknown")

# Order matters: the first match wins. BlueZ's br-* codes come from its bluetooth.h error strings; the texts are
# the bridge's own BridgeError messages.
PATTERNS = (
    (r"br-connection-key-missing|org\.bluez\.Error\.AuthenticationFailed|Authentication Failed|PIN or Key Missing", "pairing-lost"),
    (r"br-connection-page-timeout|Page Timeout|Host is down|EHOSTDOWN", "page-timeout"),
    (r"br-connection-busy|br-connection-already-connected|Operation already in progress|InProgress|Busy", "busy"),
    (r"stdin closed|cancelled by the receiver|aborted|KeyboardInterrupt", "aborted"),
    (r"timed out|TimeoutError|timeout|Timeout", "timeout"),
    (r"br-connection-canceled|br-connection-refused|Connection refused|ECONNREFUSED|Rejected", "refused"),
    (r"not paired", "not-paired"),
    (r"powered off", "powered-off"),
    (r"blocked", "blocked"),
    (r"no BlueZ adapter|multiple adapters|NoSuchAdapter", "no-adapter"),
    (r"BlueZ disappeared|D-Bus disconnected|ServiceUnknown|NameHasNoOwner", "bluez-gone"),
    (r"auth|Authentication|Permission denied|NotAuthorized", "auth-failed"),
)


def failure_reason(error):
    """The reason word for an exception or message text."""
    text = str(error) if error is not None else ""
    if not text and error is not None:
        text = type(error).__name__
    for pattern, word in PATTERNS:
        if re.search(pattern, text):
            return word
    return "unknown"


def report(error):
    """The stderr line the supervisor reads."""
    return f"bt-bridge: reason={failure_reason(error)}"
