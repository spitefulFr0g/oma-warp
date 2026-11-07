"""Check and status through the entry point, faking only the system boundary."""
import contextlib
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from oma_warp.cli import main
from oma_warp.system import System
from oma_warp import repository as repo
from test_repository import PACKAGE, metadata
from test_status import FakeSystem, status


class UpdateSystem(FakeSystem, System):
    read_json = System.read_json
    runtime_dir = None
    cache_dir = None
    def __init__(self, directory, key, signed):
        super().__init__()
        self.runtime_dir = directory / 'runtime'
        self.cache_dir = directory / 'cache'
        self.responses = {'pubkey.gpg': key, 'dists/resolute/InRelease': signed,
                          'dists/resolute/main/binary-amd64/Packages': PACKAGE,
                          'pool/resolute/warp.deb': b'data'}
        self.time = super().now()
        self.comparison = -1

    def now(self):
        return self.time

    def fetch(self, url, *, timeout, limit):
        assert url.startswith(repo.BASE_URL + '/')
        body = self.responses[url[len(repo.BASE_URL) + 1:]]
        if isinstance(body, Exception):
            raise body
        assert len(body) <= limit
        return body

    def fetch_file(self, url, destination, *, timeout, limit):
        body = self.fetch(url, timeout=timeout, limit=limit)
        destination.write_bytes(body)
        return hashlib.sha256(body).hexdigest(), len(body)

    def run(self, argv, *, timeout):
        if argv[0] == 'vercmp':
            assert argv[1] in ('2026.8.2115.0', '2026.9.1180.0')
            assert argv[2] == '2026.8.2115.0'
            return CompletedProcess(argv, 0, str(self.comparison), '')
        return super().run(argv, timeout=timeout)


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    home = tmp_path / 'signer'
    home.mkdir(mode=0o700)
    repo._gpg(home, '--pinentry-mode', 'loopback', '--passphrase', '',
              '--quick-generate-key', 'WARP test <warp@example.invalid>', 'ed25519', 'sign', '0')
    listing = repo._gpg(home, '--with-colons', '--list-keys').stdout.decode()
    fingerprint = next(line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:'))
    monkeypatch.setattr(repo, 'FINGERPRINT', fingerprint)
    key = repo._gpg(home, '--export').stdout
    (home / 'Release').write_bytes(metadata())
    repo._gpg(home, '--clearsign', str(home / 'Release'))
    yield UpdateSystem(tmp_path, key, (home / 'Release.asc').read_bytes())
    System().run_bytes(['gpgconf', '--homedir', str(home), '--kill', 'gpg-agent'], timeout=5)


def check(system, json_output=True):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(['check'] + (['--json'] if json_output else []), system=system)
    return code, json.loads(output.getvalue()) if json_output else output.getvalue()


def test_check_verifies_release_and_persists_it_across_processes(upstream):
    code, document = check(upstream)
    assert code == 0
    assert document == {'latest': '2026.8.2115.0', 'verified_at': '2026-10-02T00:00:00Z',
                        'attempted_at': '2026-10-02T00:00:00Z', 'last_error': None}
    assert upstream.read_json(upstream.cache_dir / 'update.json') == document
    assert status(upstream)['update'] == {
        'latest': '2026.8.2115.0', 'verified_at': '2026-10-02T00:00:00Z',
        'available': False, 'last_error': None, 'due': False}


@pytest.mark.parametrize(('failure', 'category'), [(OSError('offline'), 'network'),
                                                   (b'evil', 'verification')])
def test_failed_check_preserves_verified_release_and_restarts_clock(upstream, failure, category):
    assert check(upstream)[0] == 0
    upstream.time += timedelta(hours=13)
    assert status(upstream)['update']['due'] is True
    upstream.responses['pool/resolute/warp.deb'] = failure
    code, document = check(upstream)
    assert code == 1
    assert document == {'latest': '2026.8.2115.0', 'verified_at': '2026-10-02T00:00:00Z',
                        'attempted_at': '2026-10-02T13:00:00Z', 'last_error': category}
    assert status(upstream)['update'] == {
        'latest': '2026.8.2115.0', 'verified_at': '2026-10-02T00:00:00Z',
        'available': False, 'last_error': category, 'due': False}


@pytest.mark.parametrize(('name', 'comparison', 'attempt', 'error'), [
    ('update', 1, '2026-10-02T00:00:00Z', None),
    ('verify_failed', 1, '2026-10-02T00:00:00Z', 'verification'),
    ('due', 1, '2026-10-01T00:00:00Z', None),
])
def test_status_reproduces_update_fixtures(tmp_path, name, comparison, attempt, error):
    system = UpdateSystem(tmp_path, b'', b'')
    system.comparison = comparison
    system.write_json(system.cache_dir / 'update.json', {
        'latest': '2026.9.1180.0', 'verified_at': '2026-10-01T00:00:00Z',
        'attempted_at': attempt, 'last_error': error})
    fixture = json.loads((Path(__file__).parent / f'fixtures/{name}.json').read_text())
    assert status(system) == fixture


def test_successful_recheck_replaces_release_and_clears_error(upstream):
    upstream.write_json(upstream.cache_dir / 'update.json', {
        'latest': '2026.1.0', 'verified_at': '2026-01-01T00:00:00Z',
        'attempted_at': '2026-01-01T00:00:00Z', 'last_error': 'network'})
    code, output = check(upstream, json_output=False)
    assert code == 0
    assert '2026.8.2115.0' in output
    assert upstream.read_json(upstream.cache_dir / 'update.json')['last_error'] is None


@pytest.mark.parametrize(('comparison', 'available'), [(1, True), (0, False), (-1, False)])
def test_status_uses_arch_version_comparison(upstream, comparison, available):
    check(upstream)
    upstream.comparison = comparison
    assert status(upstream)['update']['available'] is available


def test_due_uses_last_attempt_including_exact_twelve_hour_boundary(upstream):
    check(upstream)
    upstream.time += timedelta(hours=12)
    assert status(upstream)['update']['due'] is False
    upstream.time += timedelta(seconds=1)
    assert status(upstream)['update']['due'] is True


def test_first_failed_check_keeps_release_unknown(upstream):
    upstream.responses['pubkey.gpg'] = OSError('offline')
    code, document = check(upstream)
    assert code == 1
    assert document['latest'] is None
    assert status(upstream)['update'] == {
        'latest': None, 'verified_at': None, 'available': None,
        'last_error': 'network', 'due': False}


@pytest.mark.parametrize('cache', [[], {'latest': []}, {'latest': '2026.9.1180.0',
    'verified_at': 'yesterday', 'attempted_at': False, 'last_error': 'unexpected'}])
def test_malformed_cache_cannot_break_status(tmp_path, cache):
    system = UpdateSystem(tmp_path, b'', b'')
    system.write_json(system.cache_dir / 'update.json', cache)
    assert status(system)['update'] == {'latest': None, 'verified_at': None,
        'available': None, 'last_error': None, 'due': True}


@pytest.mark.parametrize('failure', [KeyboardInterrupt, OSError])
@pytest.mark.parametrize('source', ['dists/resolute/InRelease',
                                   'dists/resolute/main/binary-amd64/Packages',
                                   'pool/resolute/warp.deb'])
def test_failed_fetch_persists_across_restart_and_next_success_clears_it(upstream, source, failure):
    class InterruptedSystem(UpdateSystem):
        def __init__(self):
            super().__init__(upstream.cache_dir.parent, upstream.responses['pubkey.gpg'],
                             upstream.responses['dists/resolute/InRelease'])
            self.interrupt = True
            self.scratch = []

        @contextlib.contextmanager
        def temporary_directory(self, **kwargs):
            with super().temporary_directory(**kwargs) as directory:
                self.scratch.append(Path(directory))
                yield directory

        def fetch(self, url, **kwargs):
            if self.interrupt and url == repo.BASE_URL + '/' + source:
                raise failure('fetch interrupted or offline')
            return super().fetch(url, **kwargs)

        def fetch_file(self, url, destination, **kwargs):
            # An interrupted download may already have written partial bytes.
            destination.write_bytes(b'partial')
            return super().fetch_file(url, destination, **kwargs)

    assert check(upstream)[0] == 0
    system = InterruptedSystem()
    system.time += timedelta(hours=13)
    code, document = check(system)
    assert code == 1
    assert document == {'latest': '2026.8.2115.0', 'verified_at': '2026-10-02T00:00:00Z',
                        'attempted_at': '2026-10-02T13:00:00Z', 'last_error': 'network'}
    assert all(not path.exists() for path in system.scratch)
    if source.startswith('pool/'):
        assert system.scratch
        assert {path.name for path in system.cache_dir.iterdir()} == {'update.json'}
    # A new boundary instance reads only the persisted cache, as after a shell restart.
    restarted = UpdateSystem(upstream.cache_dir.parent, b'', b'')
    restarted.time = system.time
    assert status(restarted)['update'] == {
        'latest': '2026.8.2115.0', 'verified_at': '2026-10-02T00:00:00Z',
        'available': False, 'last_error': 'network', 'due': False}
    system.interrupt = False
    system.time += timedelta(seconds=1)
    code, document = check(system)
    assert code == 0
    assert document == {'latest': '2026.8.2115.0', 'verified_at': '2026-10-02T13:00:01Z',
                        'attempted_at': '2026-10-02T13:00:01Z', 'last_error': None}
    assert status(restarted)['update']['last_error'] is None
    assert all(not path.exists() for path in system.scratch)
