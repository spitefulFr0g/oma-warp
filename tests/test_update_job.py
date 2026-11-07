"""Update Jobs through main(argv), faking only the System boundary."""
import json
from subprocess import CompletedProcess

import pytest

from oma_warp.cli import main
from test_install import InstallSystem
from test_status import status
from test_update import upstream  # noqa: F401 -- signed repository fixture


class UpdateJobSystem(InstallSystem):
    def __init__(self, upstream):
        super().__init__(upstream)
        self.installed = self.running = self.registered = True
        self.comparison = 0
        self.connection = 'Connected'
        self.after_restart = 'Connected'
        self.after_install = 'Disconnected'
        self.elapsed = 0
        self.publications = []

    def atomic_write(self, path, text):
        if path.name == 'job.json':
            self.publications.append(json.loads(text))
        super().atomic_write(path, text)

    def monotonic(self):
        return self.elapsed

    def wait(self, seconds):
        assert status(self)['job']['action'] == 'update'
        self.elapsed += seconds

    def run_terminal(self, argv, **kwargs):
        assert json.loads(self.files[self.runtime_dir / 'job.json'])['action'] == 'update'
        self.commands.append(argv)
        if argv[0].endswith('makepkg'):
            self.build_dir = kwargs['cwd']
            (self.build_dir / 'cloudflare-warp-bin-2026.8.2115.0-1-x86_64.pkg.tar.zst').write_bytes(b'package')
        elif argv[:3] == ['sudo', 'pacman', '-U']:
            assert 'download' in self.events
            self.connection = self.after_install
        elif argv == ['sudo', 'systemctl', 'restart', 'warp-svc']:
            self.connection = self.after_restart
            self.running = True
        elif argv == ['sudo', 'systemctl', 'stop', 'warp-svc']:
            self.running = False
        return CompletedProcess(argv, 0)

    def run(self, argv, *, timeout):
        if argv == ['warp-cli', '-j', 'status']:
            return CompletedProcess(argv, 0, json.dumps({'status': self.connection}), '')
        if argv in (['warp-cli', 'connect'], ['warp-cli', 'disconnect']):
            self.commands.append(argv)
            self.connection = 'Connected' if argv[-1] == 'connect' else 'Disconnected'
            return CompletedProcess(argv, 0, '', '')
        if argv[0] == 'vercmp':
            assert argv[1:] == ['2026.8.2115.0', '2026.8.2115.0']
            return CompletedProcess(argv, 0, str(self.comparison), '')
        return super().run(argv, timeout=timeout)


@pytest.mark.parametrize('comparison', [0, -1])
def test_equal_or_older_release_is_freshly_verified_cached_and_never_installed(upstream, comparison):
    system = UpdateJobSystem(upstream)
    system.comparison = comparison
    assert main(['update', '--job-id', 'current'], system=system) == 0
    assert system.messages == ['Already current']
    assert 'download' in system.events
    assert system.commands == []
    assert system.upstream.read_json(system.cache_dir / 'update.json') == {
        'latest': '2026.8.2115.0', 'verified_at': '2026-10-02T00:00:00Z',
        'attempted_at': '2026-10-02T00:00:00Z', 'last_error': None}
    assert system.scratch and all(not path.exists() for path in system.scratch)
    assert status(system)['job'] is None
    assert not system.locked



def test_newer_release_builds_installs_restores_and_cleans_under_one_job(upstream):
    system = UpdateJobSystem(upstream)
    system.comparison = 1
    assert main(['update', '--job-id', 'newer'], system=system) == 0
    assert system.commands == [
        ['/usr/bin/makepkg', '--cleanbuild', '--noconfirm'],
        ['sudo', 'pacman', '-U', str(system.build_dir / 'cloudflare-warp-bin-2026.8.2115.0-1-x86_64.pkg.tar.zst')],
        ['sudo', 'systemctl', 'restart', 'warp-svc']]
    assert system.messages == ['Connected again']
    assert len(system.publications) == 1
    assert system.publications[0]['action'] == 'update'
    assert all(not path.exists() for path in system.scratch)
    assert system.upstream.read_json(system.cache_dir / 'update.json')['latest'] == '2026.8.2115.0'
    assert [path.name for path in system.cache_dir.iterdir()] == ['update.json']
    assert status(system)['job'] is None
    assert not system.locked


@pytest.mark.parametrize(('prior', 'hook', 'restored', 'toggle', 'outcome'), [
    ('Connected', 'Disconnected', 'Disconnected', 'connect', 'Connected again'),
    ('Disconnected', 'Connected', 'Connected', 'disconnect', 'WARP did not reconnect'),
    (None, 'Connected', 'Disconnected', None, 'WARP did not reconnect'),
])
def test_restore_uses_preinstallation_connection_including_explicit_unknown(
        upstream, prior, hook, restored, toggle, outcome):
    system = UpdateJobSystem(upstream)
    system.comparison = 1
    system.connection = prior
    system.after_install = hook
    system.after_restart = restored
    assert main(['update', '--job-id', 'prior-state'], system=system) == 0
    assert [cmd for cmd in system.commands if cmd[0] == 'warp-cli'] == (
        [['warp-cli', toggle]] if toggle else [])
    assert system.messages == [outcome]
    assert system.connection == (prior if toggle else restored)


@pytest.mark.parametrize('hook_starts_service', [False, True])
def test_stopped_service_stays_stopped_even_if_package_hooks_start_it(upstream, hook_starts_service):
    class HookSystem(UpdateJobSystem):
        def run_terminal(self, argv, **kwargs):
            result = super().run_terminal(argv, **kwargs)
            if argv[:3] == ['sudo', 'pacman', '-U']:
                self.running = hook_starts_service
            return result
    system = HookSystem(upstream)
    system.comparison = 1
    system.running = False
    assert main(['update', '--job-id', 'stopped'], system=system) == 0
    assert not system.running
    assert ['sudo', 'systemctl', 'restart', 'warp-svc'] not in system.commands
    assert not any(cmd[0] == 'warp-cli' for cmd in system.commands)
    assert system.messages == ['WARP did not reconnect']


@pytest.mark.parametrize('failure', ['build', 'pacman', 'restart', 'interrupt', 'stopped-pacman'])
def test_failure_cleans_temporary_tree_and_job_and_preserves_verified_cache(upstream, failure):
    class FailedSystem(UpdateJobSystem):
        def run_terminal(self, argv, **kwargs):
            matches = ((failure in ('build', 'interrupt') and argv[0].endswith('makepkg')) or
                       (failure in ('pacman', 'stopped-pacman') and argv[:2] == ['sudo', 'pacman']) or
                       (failure == 'restart' and argv == ['sudo', 'systemctl', 'restart', 'warp-svc']))
            if matches:
                self.commands.append(argv)
                if failure == 'interrupt':
                    raise KeyboardInterrupt
                if failure == 'stopped-pacman':
                    self.running = True
                return CompletedProcess(argv, 7)
            return super().run_terminal(argv, **kwargs)
    system = FailedSystem(upstream)
    system.comparison = 1
    system.running = failure != 'stopped-pacman'
    assert main(['update', '--job-id', 'failed'], system=system) == (
        130 if failure == 'interrupt' else 1 if failure == 'build' else 7)
    assert system.scratch and all(not path.exists() for path in system.scratch)
    assert status(system)['job'] is None
    assert not system.locked
    assert system.upstream.read_json(system.cache_dir / 'update.json')['latest'] == '2026.8.2115.0'
    if failure == 'stopped-pacman':
        assert not system.running
    if failure != 'restart':
        assert ['sudo', 'systemctl', 'restart', 'warp-svc'] not in system.commands


@pytest.mark.parametrize('comparison', ['unknown', '', None])
def test_unknown_version_comparison_never_installs(upstream, comparison):
    system = UpdateJobSystem(upstream)
    system.comparison = comparison
    assert main(['update', '--job-id', 'unknown-version'], system=system) == 1
    assert not system.commands
    assert all(not path.exists() for path in system.scratch)
    assert status(system)['job'] is None


@pytest.mark.parametrize('source', ['pubkey.gpg', 'dists/resolute/InRelease',
                                   'dists/resolute/main/binary-amd64/Packages',
                                   'pool/resolute/warp.deb'])
def test_update_rejects_each_broken_verification_link_without_changing_verified_cache(upstream, source):
    system = UpdateJobSystem(upstream)
    system.comparison = 1
    previous = {'latest': '2026.1.0', 'verified_at': '2026-01-01T00:00:00Z',
                'attempted_at': '2026-01-01T00:00:00Z', 'last_error': None}
    system.write_json(system.cache_dir / 'update.json', previous)
    upstream.responses[source] = b'evil'
    assert main(['update', '--job-id', 'tampered'], system=system) == 1
    assert not system.commands
    assert all(not path.exists() for path in system.scratch)
    assert system.upstream.read_json(system.cache_dir / 'update.json') == previous
    assert status(system)['job'] is None


def test_update_contention_is_refused_before_any_verification_or_mutation(upstream):
    system = UpdateJobSystem(upstream)
    system.locked = True
    assert main(['update', '--job-id', 'contender'], system=system) == 1
    assert not system.events and not system.commands and not system.scratch
    assert not system.publications


def test_each_update_build_is_disposable_and_running_state_precedes_package_hooks(upstream):
    class HooksStopSystem(UpdateJobSystem):
        def run_terminal(self, argv, **kwargs):
            result = super().run_terminal(argv, **kwargs)
            if argv[:3] == ['sudo', 'pacman', '-U']:
                self.running = False
            return result
    system = HooksStopSystem(upstream)
    system.comparison = 1
    assert main(['update', '--job-id', 'first'], system=system) == 0
    first = system.build_dir
    assert system.running
    assert main(['update', '--job-id', 'second'], system=system) == 0
    assert system.build_dir != first
    assert all(not path.exists() for path in system.scratch)
    assert system.commands.count(['sudo', 'systemctl', 'restart', 'warp-svc']) == 2


@pytest.mark.parametrize('unknown', ['version', 'service', 'comparison-failed', 'comparison-timeout'])
def test_unknown_required_facts_refuse_install_without_discarding_verification(upstream, unknown):
    from subprocess import TimeoutExpired
    class UnknownSystem(UpdateJobSystem):
        def run(self, argv, *, timeout):
            if unknown == 'version' and argv[:2] == ['pacman', '-Qi']:
                return CompletedProcess(argv, 0, 'invalid package response', '')
            if unknown == 'service' and argv[:2] == ['systemctl', 'show']:
                return CompletedProcess(argv, 0, 'ActiveState=unknown', '')
            if argv[0] == 'vercmp':
                if unknown == 'comparison-failed':
                    return CompletedProcess(argv, 1, '1', '')
                if unknown == 'comparison-timeout':
                    raise TimeoutExpired(argv, timeout)
            return super().run(argv, timeout=timeout)
    system = UnknownSystem(upstream)
    system.comparison = 1
    assert main(['update', '--job-id', 'unknown'], system=system) == 1
    assert not system.commands
    assert all(not path.exists() for path in system.scratch)
    assert system.upstream.read_json(system.cache_dir / 'update.json')['latest'] == '2026.8.2115.0'
    assert status(system)['job'] is None


def test_failed_single_connect_reports_outcome_and_never_retries(upstream):
    class CannotConnectSystem(UpdateJobSystem):
        def run(self, argv, *, timeout):
            if argv == ['warp-cli', 'connect']:
                self.commands.append(argv)
                return CompletedProcess(argv, 1, '', 'not connected')
            return super().run(argv, timeout=timeout)
    system = CannotConnectSystem(upstream)
    system.comparison = 1
    system.after_restart = 'Disconnected'
    assert main(['update', '--job-id', 'not-restored'], system=system) == 1
    assert system.commands.count(['warp-cli', 'connect']) == 1
    assert system.commands.count(['sudo', 'systemctl', 'restart', 'warp-svc']) == 1
    assert system.messages == ['WARP did not reconnect']
    assert system.elapsed == 20
    assert all(not path.exists() for path in system.scratch)
    assert status(system)['job'] is None
