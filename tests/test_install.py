"""Install through the terminal entry point; only System effects are scripted."""
from contextlib import contextmanager
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

import pytest

from oma_warp.cli import main
from test_jobs import JobSystem
from test_update import upstream  # noqa: F401 -- shared signed repository fixture


class InstallSystem(JobSystem):
    def __init__(self, upstream):
        super().__init__()
        self.upstream = upstream
        self.cache_dir = upstream.cache_dir
        self.events = []
        self.scratch = []
        self.installed = False
        self.running = False
        self.enabled = False
        self.registered = False

    def run(self, argv, *, timeout):
        if argv[:2] == ['pacman', '-Qi'] and not self.installed:
            return CompletedProcess(argv, 1, '', "error: package 'cloudflare-warp-bin' was not found")
        if argv == ['systemctl', 'is-enabled', 'warp-svc']:
            return CompletedProcess(argv, 0 if self.enabled else 1, 'enabled' if self.enabled else 'disabled', '')
        if argv[0] == 'systemctl':
            return CompletedProcess(argv, 0, 'ActiveState=' + ('active' if self.running else 'inactive'), '')
        if argv == ['warp-cli', '-j', 'registration', 'show'] and not self.registered:
            return CompletedProcess(argv, 1, '{"error":"MissingRegistration"}', '')
        return super().run(argv, timeout=timeout)

    def fetch(self, *args, **kwargs):
        self.events.append('verify')
        return self.upstream.fetch(*args, **kwargs)

    def fetch_file(self, *args, **kwargs):
        self.events.append('download')
        return self.upstream.fetch_file(*args, **kwargs)

    def run_bytes(self, *args, **kwargs):
        return self.upstream.run_bytes(*args, **kwargs)

    @contextmanager
    def temporary_directory(self, **kwargs):
        with self.upstream.temporary_directory(**kwargs) as directory:
            self.scratch.append(Path(directory))
            yield directory

    def __getattr__(self, name):
        return getattr(self.upstream, name)

    def run_terminal(self, argv, **kwargs):
        self.events.append(argv[0])
        self.commands.append(argv)
        assert '"action": "install"' in self.files[self.runtime_dir / 'job.json']
        if argv[0].endswith('makepkg'):
            assert 'download' in self.events
            recipe = self.read_text(kwargs['cwd'] / 'PKGBUILD') if kwargs['cwd'] / 'PKGBUILD' in self.files else self.upstream.read_text(kwargs['cwd'] / 'PKGBUILD')
            assert "provides=('cloudflare-warp' 'warp-cli' 'warp-diag' 'warp-svc')" in recipe
            assert "conflicts=('cloudflare-warp')" in recipe
            hook = self.upstream.read_text(kwargs['cwd'] / 'cloudflare-warp.install')
            assert hook.count('setcap CAP_NET_ADMIN=+ei /usr/bin/warp-svc') == 2
            self.build_dir = kwargs['cwd']
            (kwargs['cwd'] / 'cloudflare-warp-bin-2026.8.2115.0-1-x86_64.pkg.tar.zst').write_bytes(b'package')
        elif argv[:3] == ['sudo', 'pacman', '-U']:
            self.installed = True
        elif argv[:3] == ['sudo', 'systemctl', 'enable']:
            self.running = self.enabled = True
        elif argv == ['warp-cli', 'registration', 'new']:
            self.registered = True
        return CompletedProcess(argv, 0)

    def run_build(self, argv, *, cwd):
        result = self.run_terminal(argv, cwd=cwd)
        return CompletedProcess(argv, result.returncode, 'build output', '')

    def effective_uid(self):
        return 1000

    def find_command(self, command):
        assert command == 'makepkg'
        return '/usr/bin/makepkg'


def test_install_verifies_builds_installs_starts_and_registers_then_cleans(upstream):
    system = InstallSystem(upstream)
    assert main(['install', '--job-id', 'example'], system=system) == 0
    assert system.commands == [
        ['/usr/bin/makepkg', '--cleanbuild', '--noconfirm'],
        ['sudo', 'pacman', '-U', str(system.build_dir / 'cloudflare-warp-bin-2026.8.2115.0-1-x86_64.pkg.tar.zst')],
        ['sudo', 'systemctl', 'enable', '--now', 'warp-svc'],
        ['warp-cli', 'registration', 'new']]
    assert system.upstream.read_json(system.cache_dir / 'update.json')['latest'] == '2026.8.2115.0'
    assert system.scratch and all(not path.exists() for path in system.scratch)
    assert system.runtime_dir / 'job.json' not in system.files


def test_existing_package_skips_verification_and_build_but_enables_running_service(upstream):
    system = InstallSystem(upstream)
    system.installed = system.running = system.registered = True
    system.enabled = False
    assert main(['install', '--job-id', 'existing'], system=system) == 0
    assert system.commands == [['sudo', 'systemctl', 'enable', '--now', 'warp-svc']]
    assert system.events == ['sudo']
    assert system.scratch == []


def test_ready_existing_client_skips_every_completed_stage(upstream):
    system = InstallSystem(upstream)
    system.installed = system.running = system.enabled = system.registered = True
    assert main(['install', '--job-id', 'ready'], system=system) == 0
    assert not system.events and not system.scratch


@pytest.mark.parametrize('failure', ['makepkg', 'pacman', 'service', 'registration', 'interrupt'])
def test_failed_install_stops_and_removes_scratch_and_job(upstream, failure):
    class FailedSystem(InstallSystem):
        def run_terminal(self, argv, **kwargs):
            matches = {
                'makepkg': argv[0].endswith('makepkg'),
                'pacman': argv[:2] == ['sudo', 'pacman'],
                'service': argv[:2] == ['sudo', 'systemctl'],
                'registration': argv == ['warp-cli', 'registration', 'new'],
                'interrupt': argv[0].endswith('makepkg'),
            }
            if matches[failure]:
                self.commands.append(argv)
                if failure == 'interrupt':
                    raise KeyboardInterrupt
                return CompletedProcess(argv, 7)
            return super().run_terminal(argv, **kwargs)
    system = FailedSystem(upstream)
    assert main(['install', '--job-id', 'failure'], system=system) == (130 if failure == 'interrupt' else 7 if failure != 'makepkg' else 1)
    expected_count = {'makepkg': 1, 'pacman': 2, 'service': 3, 'registration': 4, 'interrupt': 1}
    assert len(system.commands) == expected_count[failure]
    assert all(not path.exists() for path in system.scratch)
    assert system.runtime_dir / 'job.json' not in system.files
    assert not system.locked
    assert system.upstream.read_json(system.cache_dir / 'update.json')['latest'] == '2026.8.2115.0'


@pytest.mark.parametrize('source', ['pubkey.gpg', 'dists/resolute/InRelease',
                                   'dists/resolute/main/binary-amd64/Packages',
                                   'pool/resolute/warp.deb'])
def test_verification_failure_never_builds_or_installs_or_caches_release(upstream, source):
    system = InstallSystem(upstream)
    upstream.responses[source] = b'evil'
    assert main(['install', '--job-id', 'tampered'], system=system) == 1
    assert not system.commands
    assert all(not path.exists() for path in system.scratch)
    assert system.runtime_dir / 'job.json' not in system.files
    assert system.upstream.read_json(system.cache_dir / 'update.json') is None


@pytest.mark.parametrize('package', ['garbage', TimeoutExpired('pacman', 1.5),
    CompletedProcess([], 1, '', 'database unavailable')])
def test_unknown_installed_status_refuses_every_mutation(upstream, package):
    system = InstallSystem(upstream)
    system.installed = True
    system.outputs[('pacman', '-Qi', 'cloudflare-warp-bin')] = package
    assert main(['install', '--job-id', 'unknown'], system=system) == 1
    assert not system.events and not system.commands and not system.scratch


@pytest.mark.parametrize('unknown', ['service', 'enablement', 'registration'])
def test_unknown_later_state_is_never_treated_as_absent(upstream, unknown):
    class UnknownSystem(InstallSystem):
        def run(self, argv, *, timeout):
            if ((unknown == 'service' and argv[:2] == ['systemctl', 'show']) or
                (unknown == 'enablement' and argv[:2] == ['systemctl', 'is-enabled']) or
                (unknown == 'registration' and argv == ['warp-cli', '-j', 'registration', 'show'])):
                return CompletedProcess(argv, 0, '{}', '')
            return super().run(argv, timeout=timeout)
    system = UnknownSystem(upstream)
    system.installed = system.running = system.enabled = True
    assert main(['install', '--job-id', 'unknown'], system=system) == 1
    assert not system.commands and not system.events


def test_repeated_install_builds_in_a_new_directory_and_keeps_no_artifacts(upstream):
    system = InstallSystem(upstream)
    assert main(['install', '--job-id', 'first'], system=system) == 0
    first = system.build_dir
    system.installed = False
    assert main(['install', '--job-id', 'second'], system=system) == 0
    assert system.build_dir != first
    assert all(not path.exists() for path in system.scratch)
    assert [path.name for path in system.cache_dir.iterdir()] == ['update.json']


def test_failed_verification_keeps_previous_verified_cache(upstream):
    system = InstallSystem(upstream)
    previous = {'latest': '2026.1.0', 'verified_at': '2026-01-01T00:00:00Z',
                'attempted_at': '2026-01-01T00:00:00Z', 'last_error': None}
    system.write_json(system.cache_dir / 'update.json', previous)
    upstream.responses['pool/resolute/warp.deb'] = b'evil'
    assert main(['install', '--job-id', 'tampered'], system=system) == 1
    assert system.upstream.read_json(system.cache_dir / 'update.json') == previous
