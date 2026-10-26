"""The receiver's keystore follows the certificate of one's own (tesla_only_box_delta.md D7): wrapped while valid,
removed when gone or run out so the receiver self-signs for the bind address again."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/onecloud"))
import boxnet


@unittest.skipUnless(shutil.which("openssl"), "needs the openssl command")
class OwnCertificateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"; self.state.mkdir()
        self.work = Path(tmp.name)

    def own(self, days):
        own = self.state / "tls" / "own"; own.mkdir(parents=True, exist_ok=True)
        run = lambda *a: subprocess.run(["openssl", *a], check=True, capture_output=True, cwd=self.work)
        run("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", "ca.key",
            "-out", "ca.crt", "-days", "30", "-subj", "/CN=Public CA")
        run("req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", str(own / "key.pem"),
            "-out", "leaf.csr", "-subj", "/CN=car.example")
        (self.work / "ext").write_text("subjectAltName=DNS:car.example\n")
        run("x509", "-req", "-in", "leaf.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-days", str(days),
            "-extfile", "ext", "-out", "leaf.crt")
        (own / "fullchain.pem").write_text((self.work / "leaf.crt").read_text() + (self.work / "ca.crt").read_text())

    def served(self):
        out = subprocess.run(["openssl", "pkcs12", "-in", str(self.state / "receiver" / "tls-keystore.p12"), "-nokeys",
                              "-clcerts", "-passin", "pass:" + boxnet.KEYSTORE_PASSWORD], capture_output=True, text=True)
        if out.returncode:   # OpenSSL 3 reads the old PBE only with the legacy provider
            out = subprocess.run(["openssl", "pkcs12", "-legacy", "-in", str(self.state / "receiver" / "tls-keystore.p12"),
                                  "-nokeys", "-clcerts", "-passin", "pass:" + boxnet.KEYSTORE_PASSWORD], capture_output=True, text=True)
        return out.stdout

    def test_without_a_certificate_of_ones_own_there_is_no_keystore(self):
        # No local CA any more: the receiver makes its own self-signed certificate when the keystore is absent.
        self.assertFalse(boxnet.ensure_keystore(self.state))
        self.assertFalse(boxnet.keystore_path(self.state).exists())
        self.assertFalse((self.state / "tls" / "ca.key").exists())

    def test_a_valid_certificate_of_ones_own_is_served(self):
        self.own(60)
        self.assertTrue(boxnet.ensure_keystore(self.state))
        self.assertRegex(self.served(), r"subject=\s*CN\s*=\s*car\.example")
        self.assertEqual(boxnet.keystore_path(self.state).stat().st_mode & 0o777, 0o600)
        self.assertFalse(boxnet.ensure_keystore(self.state), "the same one is kept")
        self.own(60)   # renewed by acme.sh
        self.assertTrue(boxnet.ensure_keystore(self.state), "a renewal rewrites the keystore: the receiver restarts")

    def test_an_expired_or_removed_certificate_removes_the_keystore(self):
        self.own(60)
        boxnet.ensure_keystore(self.state)
        self.own(0)   # run out
        self.assertTrue(boxnet.ensure_keystore(self.state))
        self.assertFalse(boxnet.keystore_path(self.state).exists(), "no expired chain is served; the receiver self-signs")
        self.assertFalse(boxnet.ensure_keystore(self.state), "nothing left to change")
        self.own(60)
        boxnet.ensure_keystore(self.state)
        shutil.rmtree(self.state / "tls" / "own")   # the owner turned the name off (own_domain.forget_certificate)
        self.assertTrue(boxnet.ensure_keystore(self.state))
        self.assertFalse(boxnet.keystore_path(self.state).exists())


if __name__ == "__main__":
    unittest.main()
