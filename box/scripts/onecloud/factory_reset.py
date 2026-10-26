"""Factory reset of the box's own data (reliability_audit #24): pairings, keys, certificates, settings.

Everything under state/ that identifies this box or its iPhones is overwritten and removed: the AirPlay pairing
store and identity, the browser token, the receiver's keystore, the BlueZ link keys and the controller address,
the Let's Encrypt certificate and acme.sh account, presence and grant files, logs and diagnostics. The uci
options go back to their defaults. The MFi identity (identity/offline-mfi/) is removed only when the owner
typed the confirmation text for it: it is the one thing a reinstall cannot bring back by itself.
"""
import os
from pathlib import Path
import shutil
import subprocess

# Files whose contents are secrets: overwritten with zeros before the directory goes (best effort on flash).
SECRET_NAMES = {"pairings.properties", "airplay-identity.properties", "browser-token", "tls-keystore.p12", "key.pem",
                "account.conf", "ca.key", "identity.pk8", "certificate.p7b", "bdaddr"}
SECRET_SUFFIXES = {".key", ".pk8", ".p12", ".pem"}
IDENTITY_CONFIRMATION = "删除认证文件"
RESET_CONFIRMATION = "重置"
UCI_DEFAULTS = {"viewer_port": "", "idle_release": "300", "duckdns_domain": "", "duckdns_token": "",
                "update_check": "1", "update_mirror": ""}


def shred(path):
    """Overwrite a file's bytes with zeros, flush, then unlink."""
    try:
        size = path.stat().st_size
        with open(path, "r+b") as handle:
            handle.write(b"\0" * size)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass
    try:
        path.unlink()
    except OSError:
        pass


def wipe_tree(directory):
    directory = Path(directory)
    if not directory.exists():
        return
    for path in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_file() and not path.is_symlink() and (path.name in SECRET_NAMES or path.suffix in SECRET_SUFFIXES):
            shred(path)
    shutil.rmtree(directory, ignore_errors=True)


def wipe(root, identity=False, uci=subprocess.run, keep=("clock-floor",)):
    """Remove the box's own data under root/state (and root/identity with identity=True); reset the uci options.
    Returns the list of what went, for the log. The caller stops the service first (the supervisor restarts)."""
    root = Path(root)
    state = root / "state"
    removed = []
    if state.exists():
        for entry in sorted(state.iterdir()):
            if entry.name in keep:
                continue
            if entry.is_dir() and not entry.is_symlink():
                wipe_tree(entry)
            elif entry.name in SECRET_NAMES or entry.suffix in SECRET_SUFFIXES:
                shred(entry)
            else:
                try:
                    entry.unlink()
                except OSError:
                    pass
            removed.append(f"state/{entry.name}")
    if identity:
        wipe_tree(root / "identity" / "offline-mfi")
        (root / "identity" / "offline-mfi").mkdir(mode=0o700, parents=True, exist_ok=True)
        removed.append("identity/offline-mfi")
    for key, value in UCI_DEFAULTS.items():
        try:
            uci(["uci", "set", f"dashplay.main.{key}={value}"], capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        uci(["uci", "commit", "dashplay"], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        os.sync()
    except OSError:
        pass
    return removed
