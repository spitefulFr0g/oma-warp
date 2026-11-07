"""Build an auditable local Arch package from a verified Cloudflare WARP deb."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Protocol
from .system import System


class PackagingError(RuntimeError):
    """Raised when a verified deb cannot be prepared or packaged safely."""


class _Release(Protocol):
    version: str
    filename: str
    sha256: str
    size: int


_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*\Z")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")

# This recipe mirrors the audited cloudflare-warp-bin package at
# 42c02bdf6e55e44bd3f6384f1e0d7f70832ce9a8. All transformations are explicit.
_PKGBUILD = r'''pkgname=cloudflare-warp-bin
pkgver={version}
pkgrel=1
pkgdesc="Cloudflare WARP Client"
arch=('x86_64')
url="https://1.1.1.1"
license=('unknown')
depends=('at-spi2-core' 'ayatana-ido' 'cairo' 'curl' 'dbus' 'fontconfig' 'libcap'
         'gdk-pixbuf2' 'glib2' 'glibc' 'gtk3' 'harfbuzz' 'hicolor-icon-theme'
         'libayatana-appindicator' 'libayatana-indicator' 'libdbusmenu-glib'
         'libepoxy' 'libgcc' 'libsoup3' 'libstdc++' 'nftables' 'nspr' 'nss'
         'pango' 'tpm2-tss' 'webkit2gtk-4.1' 'zlib')
makedepends=('libarchive' 'chrpath')
provides=('cloudflare-warp' 'warp-cli' 'warp-diag' 'warp-svc')
conflicts=('cloudflare-warp')
options=('!strip')
install="cloudflare-warp.install"
source=('cloudflare-warp.deb')
noextract=('cloudflare-warp.deb')
sha256sums=('{sha256}')

prepare() {{
    mkdir -p build
    data_archive=$(bsdtar -tf cloudflare-warp.deb | awk '/^data\.tar\./ {{print; exit}}')
    if [[ -z "$data_archive" ]]; then
        echo "Could not find data.tar.* in cloudflare-warp.deb" >&2
        return 1
    fi
    bsdtar -xOf cloudflare-warp.deb "$data_archive" | bsdtar -xf - -C build
    sed -e "s%ExecStart=/bin/warp-svc%ExecStart=/usr/bin/warp-svc%" \
        -i build/lib/systemd/system/warp-svc.service
    sed -e "s%ExecStart=/bin/warp-taskbar%ExecStart=/usr/bin/warp-taskbar%" \
        -e "s%BindsTo=graphical-session.target%PartOf=graphical-session.target%" \
        -i build/usr/lib/systemd/user/warp-taskbar.service
    chrpath --delete build/usr/lib/warp/lib/{{crashpad_handler,libdartjni.so}}
    chrpath --replace /usr/lib/warp/lib build/usr/lib/warp/lib/*plugin.so
}}

package() {{
    cp -R build/{{etc,usr}} "${{pkgdir}}"
    cp -R build/{{bin,lib}} "${{pkgdir}}/usr"
}}
'''

_INSTALL = '''post_install() {
    setcap CAP_NET_ADMIN=+ei /usr/bin/warp-svc
}

post_upgrade() {
    setcap CAP_NET_ADMIN=+ei /usr/bin/warp-svc
}
'''


def prepare_build(release: _Release, deb: Path, output: Path, *, system=None) -> Path:
    """Create a new build directory containing the audited recipe and verified deb."""
    system = system if system is not None else System()
    try:
        version = release.version
        filename = release.filename
        expected_hash = release.sha256
        expected_size = release.size
    except AttributeError as exc:
        raise PackagingError("release must provide version, filename, sha256, and size") from exc
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise PackagingError("release version must contain only numeric dot-separated components")
    if (
        not isinstance(filename, str)
        or not filename
        or filename.startswith("/")
        or "\\" in filename
        or any(part in ("", ".", "..") for part in filename.split("/"))
    ):
        raise PackagingError("release filename must be a safe relative repository path")
    if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
        raise PackagingError("release sha256 must be 64 hexadecimal characters")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
        raise PackagingError("release size must be a non-negative integer")

    deb = Path(deb)
    if not system.is_file(deb):
        raise PackagingError(f"verified deb does not exist: {deb}")
    actual_hash, actual_size = system.digest(deb)
    if actual_hash.lower() != expected_hash.lower() or actual_size != expected_size:
        raise PackagingError("deb checksum or size does not match the verified release")

    output = Path(output)
    system.make_directory(output)
    try:
        build_dir = system.make_temporary_directory(prefix=f"cloudflare-warp-{version}-", dir=output)
        system.copy_file(deb, build_dir / "cloudflare-warp.deb")
        system.write_text(build_dir / "PKGBUILD",
            _PKGBUILD.format(version=version, sha256=actual_hash), encoding="utf-8"
        )
        system.write_text(build_dir / "cloudflare-warp.install", _INSTALL, encoding="utf-8")
    except OSError as exc:
        raise PackagingError(f"could not prepare package build directory: {exc}") from exc
    return build_dir


def build_package(build_dir: Path, *, system=None) -> Path:
    """Run makepkg as an ordinary user and return the resulting package file."""
    system = system if system is not None else System()
    build_dir = system.resolve_path(Path(build_dir))
    if system.effective_uid() == 0:
        raise PackagingError("makepkg must not be run as root; run this command as your regular user")
    if not system.is_directory(build_dir) or not system.is_file(build_dir / "PKGBUILD"):
        raise PackagingError(f"not a prepared build directory: {build_dir}")
    makepkg = system.find_command("makepkg")
    if makepkg is None:
        raise PackagingError("makepkg is unavailable; install the Arch base-devel package group")
    try:
        result = system.run_build([makepkg, "--cleanbuild", "--syncdeps"], cwd=build_dir)
    except OSError as exc:
        raise PackagingError(f"could not start makepkg: {exc}") from exc
    if result.returncode:
        output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        if any(marker in output for marker in ("missing dependencies", "could not satisfy dependencies", "not found")):
            guidance = "Install the missing build dependencies (including libarchive and chrpath), then retry."
        else:
            guidance = "Review the makepkg output above, confirm dependency installation when prompted, and retry."
        details = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
        if len(details) > 4000:
            details = details[-4000:]
        suffix = f"\n{details}" if details else ""
        raise PackagingError(f"makepkg failed with exit status {result.returncode}. {guidance}{suffix}")

    packages = sorted(system.glob(build_dir, "cloudflare-warp-bin-*.pkg.tar.*"))
    packages = [p for p in packages if system.is_file(p) and not p.name.endswith((".sig", ".sigstore"))]
    if not packages:
        raise PackagingError("makepkg succeeded but produced no cloudflare-warp-bin package")
    return packages[-1]
