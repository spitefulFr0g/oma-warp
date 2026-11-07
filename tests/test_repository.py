import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from oma_warp import repository as repo
from oma_warp.system import System


class DownloadSystem(System):
    def __init__(self, body):
        self.body = body

    def fetch_file(self, url, destination, *, timeout, limit):
        destination.write_bytes(self.body)
        return hashlib.sha256(self.body).hexdigest(), len(self.body)


PACKAGE = b"""Package: cloudflare-warp
Version: 2026.8.2115.0
Architecture: amd64
Filename: pool/resolute/warp.deb
Size: 4
SHA256: 3a6eb0790f39ac87c94f3856b2dd2c5d110e6811602261a9a923d3bb23adc8b7
"""


def metadata(index=PACKAGE, extra="", suite="resolute"):
    return (f"Suite: {suite}\nCodename: {suite}\nDate: Thu, 01 Jan 2026 00:00:00 UTC\n"
            f"{extra}SHA256:\n {hashlib.sha256(index).hexdigest()} {len(index)} main/binary-amd64/Packages\n").encode()


class RepositoryTests(unittest.TestCase):
    def latest(self, index=PACKAGE, signed=None):
        with patch.object(repo, "_fetch", side_effect=[b"key", b"signed", index]), \
             patch.object(repo, "_verify_inrelease", return_value=signed or metadata(index)):
            return repo.Repository().latest()

    def test_verified_index_selects_version_numerically(self):
        newer = PACKAGE.replace(b"2026.8.2115.0", b"2026.10.1.0")
        selected = self.latest(PACKAGE + b"\n" + newer)
        self.assertEqual(selected.version, "2026.10.1.0")

    def test_modified_index_rejected(self):
        with self.assertRaisesRegex(repo.RepositoryError, "SHA256 mismatch"):
            self.latest(PACKAGE.replace(b"2115", b"9999"), metadata())

    def test_wrong_signed_suite_rejected(self):
        with self.assertRaisesRegex(repo.RepositoryError, "suite"):
            self.latest(signed=metadata(suite="noble"))

    def test_expired_signed_metadata_rejected(self):
        with self.assertRaisesRegex(repo.RepositoryError, "expired"):
            self.latest(signed=metadata(extra="Valid-Until: Thu, 01 Jan 2026 01:00:00 UTC\n"))

    def test_future_metadata_rejected(self):
        with self.assertRaisesRegex(repo.RepositoryError, "future"):
            self.latest(signed=metadata().replace(b"01 Jan 2026", b"01 Jan 2099"))

    def test_signed_package_traversal_rejected(self):
        with self.assertRaisesRegex(repo.RepositoryError, "Unsafe"):
            self.latest(PACKAGE.replace(b"pool/resolute/warp.deb", b"pool/../warp.deb"))

    def test_unexpected_version_syntax_rejected(self):
        with self.assertRaisesRegex(repo.RepositoryError, "version"):
            self.latest(PACKAGE.replace(b"2026.8.2115.0", b"$(touch bad)"))

    def test_wrong_architecture_not_selected(self):
        with self.assertRaisesRegex(repo.RepositoryError, "not in"):
            self.latest(PACKAGE.replace(b"amd64", b"arm64"))

    def test_paths_reject_urls_escapes_and_normalization(self):
        for path in ("https://evil/deb", "//evil/path", "pool/%2e%2e/file", "pool//file", "pool/./file", "../a", "/pool/a", "pool/a?b"):
            with self.subTest(path=path), self.assertRaises(repo.RepositoryError):
                repo._safe_path(path)

    def test_download_tampering_does_not_replace_existing_file(self):
        release = repo._release(repo._paragraphs(PACKAGE)[0])
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            target = destination / "warp.deb"
            target.write_bytes(b"existing")
            with self.assertRaisesRegex(repo.RepositoryError, "SHA256"):
                repo.Repository(system=DownloadSystem(b"evil")).download(release, destination)
            self.assertEqual(target.read_bytes(), b"existing")
            self.assertEqual(list(destination.iterdir()), [target])

    def test_download_verified_bytes(self):
        release = repo._release(repo._paragraphs(PACKAGE)[0])
        with tempfile.TemporaryDirectory() as directory:
            target = repo.Repository(system=DownloadSystem(b"data")).download(release, Path(directory))
            self.assertEqual(target.read_bytes(), b"data")


class SignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.home = Path(cls.scratch.name)
        cls.home.chmod(0o700)
        repo._gpg(cls.home, "--pinentry-mode", "loopback", "--passphrase", "",
                  "--quick-generate-key", "WARP test <warp@example.invalid>", "ed25519", "sign", "0")
        listed = repo._gpg(cls.home, "--with-colons", "--list-keys").stdout.decode()
        cls.fingerprint = next(line.split(":")[9] for line in listed.splitlines() if line.startswith("fpr:"))
        cls.key = repo._gpg(cls.home, "--export").stdout
        plaintext = cls.home / "Release"
        plaintext.write_bytes(metadata())
        repo._gpg(cls.home, "--clearsign", str(plaintext))
        cls.signed = (cls.home / "Release.asc").read_bytes()

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--homedir", str(cls.home), "--kill", "gpg-agent"], capture_output=True)
        cls.scratch.cleanup()

    def test_unknown_signing_key_rejected(self):
        with self.assertRaisesRegex(repo.RepositoryError, "fingerprint changed"):
            repo._verify_inrelease(self.key, self.signed)

    def test_real_signature_verifies_when_pinned(self):
        with patch.object(repo, "FINGERPRINT", self.fingerprint):
            self.assertEqual(repo._verify_inrelease(self.key, self.signed), metadata())

    def test_modified_signed_release_rejected(self):
        with patch.object(repo, "FINGERPRINT", self.fingerprint):
            with self.assertRaisesRegex(repo.RepositoryError, "GPG verification failed"):
                repo._verify_inrelease(self.key, self.signed.replace(b"resolute", b"malicious"))


if __name__ == "__main__":
    unittest.main()
