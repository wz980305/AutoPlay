"""TLS keystore for the receiver (openssl CLI).

The box has no CA of its own any more (tesla_only_box_delta.md D7): a Tesla cannot install one, and the receiver
(PlayPort TlsCertificate.kt) makes itself a self-signed certificate with the bind address in its SAN whenever no
keystore exists, which is all the unverified IP route needs. What stays is the certificate of one's own: the
Let's Encrypt chain own_domain.py obtains for the own name (DuckDNS or DNSPod), wrapped into the PKCS12 keystore the receiver
loads (alias and password "playport", fixed in its source). When that certificate is gone or has run out, the
keystore is deleted so that the receiver self-signs again instead of serving an expired chain.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

KEYSTORE_ALIAS = "playport"
KEYSTORE_PASSWORD = "playport"   # constant in PlayPort's TlsCertificate.kt; protects nothing
RENEW_DAYS = 30                  # own_domain renews this long before the certificate runs out (by the box clock)


def _openssl(*args, cwd=None):
    subprocess.run(["openssl", *args], check=True, cwd=cwd, capture_output=True, timeout=120)


def _leaf_current(leaf: Path, days=RENEW_DAYS) -> bool:
    """The certificate stays valid for `days` more (a box without a clock may run behind; it renews late)."""
    if not leaf.exists():
        return False
    out = subprocess.run(["openssl", "x509", "-checkend", str(days * 86400), "-noout", "-in", str(leaf)],
                         capture_output=True, timeout=30)
    return out.returncode == 0


def keystore_path(state: Path):
    return Path(state) / "receiver" / "tls-keystore.p12"


def _keystore(state: Path, key: Path, chain: Path):
    """The PKCS12 keystore the PlayPort server loads, written atomically."""
    keystore = keystore_path(state)
    tls = state / "tls"
    tls.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tls) as work:
        # One PBKDF2/MAC iteration: the password is public (see tls.security); 10000 cost ~2.7 s/start.
        _openssl("pkcs12", "-export", "-inkey", str(key), "-in", str(chain),
                 "-name", KEYSTORE_ALIAS, "-passout", f"pass:{KEYSTORE_PASSWORD}",
                 "-keypbe", "AES-256-CBC", "-certpbe", "AES-256-CBC", "-macalg", "sha256",
                 "-iter", "1", "-nomaciter", "-out", "tls-keystore.p12", cwd=Path(work))
        keystore.parent.mkdir(parents=True, exist_ok=True)
        target = keystore.with_suffix(".p12.new")
        (Path(work) / "tls-keystore.p12").replace(target)
        target.chmod(0o600)
        target.replace(keystore)


def own_certificate(state: Path):
    """state/tls/own/{fullchain,key}.pem (Let's Encrypt for the DuckDNS name, renewed by acme.sh), served while
    it is valid for one more day; else None."""
    own = Path(state) / "tls" / "own"
    chain, key = own / "fullchain.pem", own / "key.pem"
    return (chain, key) if key.exists() and _leaf_current(chain, days=1) else None


def ensure_keystore(state: Path):
    """Keep the receiver's keystore in step with the certificate of one's own. Returns True when the keystore
    was written or removed, i.e. the receiver has to restart to pick the change up (it reads it once)."""
    state = Path(state).resolve()   # openssl runs in a scratch directory
    marker = state / "tls" / "leaf.san.json"
    keystore = keystore_path(state)
    own = own_certificate(state)
    if own:
        wanted = json.dumps({"own": hashlib.sha256(own[0].read_bytes()).hexdigest()[:16]})
        if keystore.exists() and marker.exists() and marker.read_text() == wanted:
            return False
        _keystore(state, own[1], own[0])
        marker.write_text(wanted)
        return True
    # No certificate of one's own (none yet, removed, or run out): the receiver self-signs for the bind address.
    changed = keystore.exists() or marker.exists()
    keystore.unlink(missing_ok=True)
    marker.unlink(missing_ok=True)
    return changed
