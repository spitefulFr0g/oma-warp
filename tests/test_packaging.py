import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from oma_warp import packaging


class PrepareBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.deb = self.root / "verified.deb"
        self.payload = b"verified package bytes"
        self.deb.write_bytes(self.payload)
        self.release = SimpleNamespace(
            version="2026.8.2115.0",
            filename="pool/resolute/main/c/cloudflare-warp/cloudflare-warp_2026.8.2115.0_amd64.deb",
            sha256=hashlib.sha256(self.payload).hexdigest(),
            size=len(self.payload),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_rejects_checksum_mismatch(self):
        self.release.sha256 = "0" * 64
        with self.assertRaisesRegex(packaging.PackagingError, "checksum or size"):
            packaging.prepare_build(self.release, self.deb, self.root / "out")

    def test_generates_audited_recipe_without_metadata_injection(self):
        self.release.version = "2026.1;touch /tmp/injected"
        with self.assertRaisesRegex(packaging.PackagingError, "numeric"):
            packaging.prepare_build(self.release, self.deb, self.root / "out")
        self.release.version = "2026.8.2115.0"
        directory = packaging.prepare_build(self.release, self.deb, self.root / "out")
        recipe = (directory / "PKGBUILD").read_text()
        self.assertIn("pkgname=cloudflare-warp-bin", recipe)
        self.assertIn("PartOf=graphical-session.target", recipe)
        self.assertIn("s%BindsTo=graphical-session.target%PartOf=graphical-session.target%", recipe)
        self.assertIn("noextract=('cloudflare-warp.deb')", recipe)
        self.assertIn("data.tar.", recipe)
        self.assertIn("sha256sums=('" + self.release.sha256 + "')", recipe)
        self.assertEqual((directory / "cloudflare-warp.deb").read_bytes(), self.payload)

    def test_rejects_unsafe_repository_path(self):
        self.release.filename = "pool/../outside.deb"
        with self.assertRaisesRegex(packaging.PackagingError, "safe relative"):
            packaging.prepare_build(self.release, self.deb, self.root / "out")


class BuildPackageTests(unittest.TestCase):
    def test_reports_makepkg_dependency_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            build_dir = Path(temp)
            (build_dir / "PKGBUILD").write_text("pkgname=cloudflare-warp-bin")
            result = subprocess.CompletedProcess([], 1, "make output", "missing dependencies: chrpath")
            with patch.object(packaging.os, "geteuid", return_value=1000), patch.object(
                packaging.shutil, "which", return_value="/usr/bin/makepkg"
            ), patch.object(packaging.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(packaging.PackagingError, "Install the missing build dependencies") as error:
                    packaging.build_package(build_dir)
                self.assertIn("make output", str(error.exception))
                self.assertIn("missing dependencies: chrpath", str(error.exception))


if __name__ == "__main__":
    unittest.main()
