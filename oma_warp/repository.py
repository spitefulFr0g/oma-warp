"""Verify Cloudflare's signed APT repository without trusting AUR or a local keyring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from email.utils import parsedate_to_datetime
import gzip
import hashlib
from http.client import HTTPException
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.error import URLError
from .system import System


BASE_URL = "https://pkg.cloudflareclient.com"
FINGERPRINT = "C068A2B5771775193CBE1F2F6E2DD2174FA1C3BA"
METADATA_LIMIT = 32 * 1024 * 1024
VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+)+(?:-[0-9]+)?\Z")


class RepositoryError(RuntimeError):
    """The upstream could not be fetched or its trust chain did not verify."""


class NetworkError(RepositoryError):
    """The repository could not be reached."""


@dataclass(frozen=True)
class Release:
    version: str
    filename: str
    sha256: str
    size: int
    architecture: str = "amd64"


def _safe_path(path: str) -> str:
    # Reject percent escapes as well as URL syntax; decoding must not change meaning.
    if not re.fullmatch(r"[A-Za-z0-9_./+~-]+", path):
        raise RepositoryError(f"Unsafe repository path: {path!r}")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or str(parsed) != path:
        raise RepositoryError(f"Unsafe repository path: {path!r}")
    return path


def _fetch(path: str, limit: int = METADATA_LIMIT, *, system=None) -> bytes:
    system = system if system is not None else System()
    try:
        return system.fetch(f"{BASE_URL}/{_safe_path(path)}", timeout=8, limit=limit)
    except (URLError, OSError, HTTPException) as exc:
        raise NetworkError(f"Unable to fetch {path}: {exc}") from exc
    except ValueError as exc:
        raise RepositoryError(str(exc)) from exc


def _gpg(home: Path, *args: str, system=None) -> subprocess.CompletedProcess:
    try:
        result = (system if system is not None else System()).run_bytes(
            ["gpg", "--no-options", "--homedir", str(home), "--batch", "--no-tty", *args], timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RepositoryError(f"Cannot run gpg: {exc}") from exc
    if result.returncode:
        raise RepositoryError(f"GPG verification failed: {result.stderr.decode(errors='replace').strip()}")
    return result


def _verify_inrelease(key: bytes, inrelease: bytes, *, system=None) -> bytes:
    system = system if system is not None else System()
    def gpg(home, *args):
        return _gpg(home, *args, system=system)
    with system.temporary_directory(prefix="oma-warp-verify-") as scratch:
        home = Path(scratch)
        system.chmod(home, 0o700)
        keyfile = home / "cloudflare.gpg"
        system.write_bytes(keyfile, key)
        listing = gpg(home, "--with-colons", "--import-options", "show-only", "--import", str(keyfile))
        fingerprints = []
        primary = False
        for line in listing.stdout.decode().splitlines():
            fields = line.split(":")
            if fields[0] in ("pub", "sub"):
                primary = fields[0] == "pub"
            elif fields[0] == "fpr" and primary:
                fingerprints.append(fields[9])
                primary = False
        if fingerprints != [FINGERPRINT]:
            raise RepositoryError("Cloudflare signing key fingerprint changed; refusing automatic trust")
        gpg(home, "--import", str(keyfile))
        signed = home / "InRelease"
        system.write_bytes(signed, inrelease)
        result = gpg(home, "--status-fd", "2", "--output", str(home / "Release"), "--decrypt", str(signed))
        statuses = result.stderr.decode(errors="replace").splitlines()
        valid = [line.split() for line in statuses if line.startswith("[GNUPG:] VALIDSIG ")]
        if len(valid) != 1 or (valid[0][-1] != FINGERPRINT and valid[0][2] != FINGERPRINT):
            raise RepositoryError("InRelease was not signed by the pinned Cloudflare key")
        if any(line.startswith(tuple(f"[GNUPG:] {tag} " for tag in (
            "BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG", "KEYEXPIRED", "SIGEXPIRED"
        ))) for line in statuses):
            raise RepositoryError("InRelease signature is expired, revoked, or invalid")
        return system.read_bytes(home / "Release")


def _paragraphs(data: bytes) -> list[dict[str, str]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepositoryError("Repository metadata is not UTF-8") from exc
    records: list[dict[str, str]] = []
    record: dict[str, str] = {}
    previous = None
    for line in text.splitlines() + [""]:
        if not line:
            if record:
                records.append(record)
            record, previous = {}, None
        elif line[0].isspace():
            if previous is None:
                raise RepositoryError("Malformed continuation in repository metadata")
            record[previous] += "\n" + line.strip()
        else:
            name, separator, value = line.partition(":")
            if not separator or name in record:
                raise RepositoryError("Malformed or duplicate repository metadata field")
            record[name] = value.strip()
            previous = name
    return records


def _verify_digest(data: bytes, sha256: str, size: int, name: str) -> None:
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
        raise RepositoryError(f"Size or SHA256 mismatch for {name}")


def _version_key(version: str) -> tuple[tuple[int, ...], int]:
    if not VERSION_RE.fullmatch(version):
        raise RepositoryError(f"Unsupported upstream version format: {version!r}")
    upstream, _, revision = version.partition("-")
    components = [int(part) for part in upstream.split(".")]
    while components and components[-1] == 0:
        components.pop()
    return tuple(components), int(revision or "0")


def _release(record: dict[str, str]) -> Release:
    try:
        version = record["Version"]
        _version_key(version)
        filename = _safe_path(record["Filename"])
        digest = record["SHA256"]
        size = int(record["Size"])
        if not filename.startswith("pool/") or not filename.endswith(".deb"):
            raise RepositoryError("Package filename must be a .deb under pool/")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not 0 < size < 2 * 1024**3:
            raise RepositoryError("Invalid package SHA256 or size")
        if record["Package"] != "cloudflare-warp" or record["Architecture"] != "amd64":
            raise RepositoryError("Unexpected package identity")
        return Release(version, filename, digest, size)
    except (KeyError, ValueError) as exc:
        raise RepositoryError("Incomplete package metadata") from exc


class Repository:
    def __init__(self, *, system=None):
        self.system = system
        self.suite = "resolute"
        self.evidence: dict = {}

    def latest(self) -> Release:
        # Keep the audited verification seam available to its regression tests.
        def fetch(path):
            return _fetch(path) if self.system is None else _fetch(path, system=self.system)
        key = fetch("pubkey.gpg")
        signed = fetch(f"dists/{self.suite}/InRelease")
        verified = (_verify_inrelease(key, signed) if self.system is None else
                    _verify_inrelease(key, signed, system=self.system))
        records = _paragraphs(verified)
        if len(records) != 1:
            raise RepositoryError("Expected one signed Release record")
        metadata = records[0]
        if metadata.get("Suite") != self.suite or metadata.get("Codename") != self.suite:
            raise RepositoryError("Signed repository suite does not match request")
        now = (self.system if self.system is not None else System()).now()
        for field in ("Date", "Valid-Until"):
            if field not in metadata:
                if field == "Date":
                    raise RepositoryError("Signed metadata has no Date")
                continue
            try:
                date = parsedate_to_datetime(metadata[field])
                if date.tzinfo is None:
                    raise ValueError("timezone required")
            except (ValueError, TypeError) as exc:
                raise RepositoryError(f"Invalid signed {field}") from exc
            if field == "Date" and date > now + timedelta(minutes=10):
                raise RepositoryError("Signed metadata Date is in the future; check the system clock")
            if field == "Valid-Until" and date <= now:
                raise RepositoryError("Signed repository metadata has expired")
        hashes = {}
        for line in metadata.get("SHA256", "").splitlines():
            if not line.strip():
                continue
            try:
                digest, size, filename = line.split()
                size = int(size)
            except ValueError as exc:
                raise RepositoryError("Malformed signed SHA256 entry") from exc
            if not re.fullmatch(r"[0-9a-f]{64}", digest) or not 0 < size <= METADATA_LIMIT or filename in hashes:
                raise RepositoryError("Invalid or duplicate signed SHA256 entry")
            hashes[filename] = (digest, size)
        plain = "main/binary-amd64/Packages"
        index_path = next((p for p in (plain, plain + ".gz") if p in hashes), None)
        if index_path is None:
            raise RepositoryError("Signed repository has no amd64 Packages SHA256")
        index = fetch(f"dists/{self.suite}/{index_path}")
        _verify_digest(index, *hashes[index_path], index_path)
        index_hash = hashlib.sha256(index).hexdigest()
        if index_path.endswith(".gz"):
            try:
                # Bound decompression to avoid unbounded allocation even for signed data.
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(index)) as zipped:
                    index = zipped.read(METADATA_LIMIT + 1)
            except (OSError, EOFError) as exc:
                raise RepositoryError("Invalid compressed Packages index") from exc
            if len(index) > METADATA_LIMIT:
                raise RepositoryError("Decompressed Packages index is too large")
        releases = [_release(r) for r in _paragraphs(index)
                    if r.get("Package") == "cloudflare-warp" and r.get("Architecture") == "amd64"]
        if not releases:
            raise RepositoryError("Requested cloudflare-warp version is not in the signed amd64 index")
        selected = max(releases, key=lambda release: _version_key(release.version))
        self.evidence = {
            "repository": BASE_URL, "suite": self.suite, "signing_fingerprint": FINGERPRINT,
            "inrelease_sha256": hashlib.sha256(signed).hexdigest(), "packages_sha256": index_hash,
            "repository_date": metadata["Date"], "valid_until": metadata.get("Valid-Until"),
        }
        return selected

    def download(self, release: Release, destination: Path) -> Path:
        # Validate even manually constructed Release instances before using paths.
        _release({"Version": release.version, "Filename": release.filename,
                  "SHA256": release.sha256, "Size": str(release.size),
                  "Architecture": release.architecture, "Package": "cloudflare-warp"})
        system = self.system if self.system is not None else System()
        destination = Path(destination)
        system.make_directory(destination)
        target = destination / PurePosixPath(release.filename).name
        with system.temporary_directory(prefix="oma-warp-download-", dir=destination) as scratch:
            temporary = Path(scratch) / "package.deb"
            try:
                digest, size = system.fetch_file(f"{BASE_URL}/{release.filename}", temporary,
                                                 timeout=8, limit=release.size)
            except (URLError, OSError, HTTPException) as exc:
                raise NetworkError(f"Unable to download package: {exc}") from exc
            except ValueError as exc:
                raise RepositoryError(str(exc)) from exc
            if size != release.size or digest != release.sha256:
                raise RepositoryError("Downloaded package size or SHA256 does not match signed metadata")
            system.replace(temporary, target)
        return target
