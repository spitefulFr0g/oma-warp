"""Uninstall scenarios at the terminal entry point; no host effects."""
from pathlib import Path
from subprocess import CompletedProcess

from oma_warp.cli import main


class FakeSystem:
    cache_dir = Path('/unused/cache')
    runtime_dir = Path('/unused/runtime')
    plugin_dir = Path('/unused/plugin')

    def __init__(self, answer=False):
        self.answer = answer
        self.events = []
        self.messages = []
        self.package = True
        self.active = True
        self.enabled = True
        self.connection = 'Connected'
        self.registered = True
        self.paths = {self.cache_dir, self.runtime_dir, self.plugin_dir,
                      Path('/var/lib/cloudflare-warp')}
        self.fail = None
        self.outputs = {}

    def confirm(self, prompt):
        self.events.append('confirm')
        return self.answer

    def write(self, message):
        self.messages.append(message)

    def run(self, argv, *, timeout):
        command = tuple(argv)
        if command in self.outputs:
            value = self.outputs[command]
            if isinstance(value, Exception):
                raise value
            return value
        if argv == ['pacman', '-Qq', 'cloudflare-warp-bin']:
            return CompletedProcess(argv, 0 if self.package else 1,
                                    'cloudflare-warp-bin\n' if self.package else '',
                                    '' if self.package else "error: package 'cloudflare-warp-bin' was not found\n")
        if argv[:3] == ['systemctl', 'show', 'warp-svc']:
            return CompletedProcess(argv, 0, 'LoadState=' + ('loaded' if self.package else 'not-found') +
                                    '\nActiveState=' + ('active' if self.active else 'inactive') +
                                    '\nUnitFileState=' + ('enabled' if self.enabled else 'disabled') + '\n', '')
        if argv == ['warp-cli', '-j', 'status']:
            return CompletedProcess(argv, 0, '{"status":"' + self.connection + '"}', '')
        if argv == ['warp-cli', '-j', 'registration', 'show']:
            return CompletedProcess(argv, 0 if self.registered else 1,
                                    '{"id":"placeholder"}' if self.registered else '{"error":"MissingRegistration"}', '')
        raise AssertionError(f'unexpected query: {argv}')

    def run_terminal(self, argv):
        command = tuple(argv)
        self.events.append(command)
        if command == self.fail:
            return CompletedProcess(argv, 1)
        if argv == ['warp-cli', 'disconnect']:
            self.connection = 'Disconnected'
        elif argv == ['warp-cli', 'registration', 'delete']:
            self.registered = False
        elif argv == ['sudo', 'systemctl', 'stop', 'warp-svc']:
            self.active = False
        elif argv == ['sudo', 'systemctl', 'disable', 'warp-svc']:
            self.enabled = False
        elif argv == ['sudo', 'pacman', '-Rns', '--noconfirm', 'cloudflare-warp-bin']:
            self.package = False
        elif argv == ['sudo', 'rm', '-rf', '--', '/var/lib/cloudflare-warp']:
            self.paths.discard(Path('/var/lib/cloudflare-warp'))
        elif argv == ['omarchy', 'plugin', 'remove', 'spitefulfr0g.oma-warp', '--yes']:
            self.paths.discard(self.plugin_dir)
        else:
            raise AssertionError(f'unexpected removal: {argv}')
        return CompletedProcess(argv, 0)

    def path_exists(self, path):
        return path in self.paths

    def remove_tree(self, path):
        self.events.append(('remove_tree', path))
        self.paths.discard(path)


def test_declining_uninstall_changes_nothing():
    system = FakeSystem()
    assert main(['uninstall'], system=system) == 0
    assert system.events == ['confirm']


def test_full_removal_is_ordered_after_one_confirmation():
    system = FakeSystem(answer=True)
    assert main(['uninstall'], system=system) == 0
    assert system.events == [
        'confirm',
        ('warp-cli', 'disconnect'),
        ('warp-cli', 'registration', 'delete'),
        ('sudo', 'systemctl', 'stop', 'warp-svc'),
        ('sudo', 'systemctl', 'disable', 'warp-svc'),
        ('sudo', 'pacman', '-Rns', '--noconfirm', 'cloudflare-warp-bin'),
        ('sudo', 'rm', '-rf', '--', '/var/lib/cloudflare-warp'),
        ('remove_tree', system.cache_dir),
        ('remove_tree', system.runtime_dir),
        ('omarchy', 'plugin', 'remove', 'spitefulfr0g.oma-warp', '--yes'),
    ]
    assert not system.paths
    assert not system.package


def test_resume_after_registration_was_deleted_skips_completed_steps():
    system = FakeSystem(answer=True)
    system.fail = ('sudo', 'systemctl', 'stop', 'warp-svc')
    assert main(['uninstall'], system=system) == 1
    assert system.events[-1] == system.fail
    assert system.package and system.paths
    system.events.clear()
    system.fail = None
    system.outputs[('warp-cli', '-j', 'status')] = CompletedProcess(
        [], 1, '{"error":"MissingRegistration"}', '')
    assert main(['uninstall'], system=system) == 0
    assert system.events[:3] == [
        'confirm', ('sudo', 'systemctl', 'stop', 'warp-svc'),
        ('sudo', 'systemctl', 'disable', 'warp-svc'),
    ]
    assert not system.paths


def test_already_clean_machine_only_confirms():
    system = FakeSystem(answer=True)
    system.package = system.active = system.enabled = system.registered = False
    system.paths.clear()
    assert main(['uninstall'], system=system) == 0
    assert system.events == ['confirm']


def test_each_terminal_failure_stops_cleanup_and_next_run_resumes():
    commands = [
        ('warp-cli', 'disconnect'),
        ('warp-cli', 'registration', 'delete'),
        ('sudo', 'systemctl', 'stop', 'warp-svc'),
        ('sudo', 'systemctl', 'disable', 'warp-svc'),
        ('sudo', 'pacman', '-Rns', '--noconfirm', 'cloudflare-warp-bin'),
        ('sudo', 'rm', '-rf', '--', '/var/lib/cloudflare-warp'),
        ('omarchy', 'plugin', 'remove', 'spitefulfr0g.oma-warp', '--yes'),
    ]
    for command in commands:
        system = FakeSystem(answer=True)
        system.fail = command
        assert main(['uninstall'], system=system) == 1
        assert system.events[-1] == command
        assert 'stopped' in system.messages[-1]
        completed = system.events[1:-1]
        system.events.clear()
        system.fail = None
        assert main(['uninstall'], system=system) == 0
        assert not system.paths
        assert not any(event in system.events for event in completed)


def test_unknown_fact_sources_stop_instead_of_claiming_already_done():
    from subprocess import TimeoutExpired
    queries = [
        ('pacman', '-Qq', 'cloudflare-warp-bin'),
        ('systemctl', 'show', 'warp-svc', '--property=LoadState,ActiveState,UnitFileState'),
        ('warp-cli', '-j', 'status'),
        ('warp-cli', '-j', 'registration', 'show'),
    ]
    for query in queries:
        for result in (FileNotFoundError('command unavailable'), TimeoutExpired(query, 1.5),
                       CompletedProcess(query, 1, '', 'source unavailable'),
                       CompletedProcess(query, 0, 'malformed', '')):
            system = FakeSystem(answer=True)
            system.outputs[query] = result
            assert main(['uninstall'], system=system) == 1
            assert system.package and system.paths
            assert not any(event[0] in ('sudo', 'omarchy', 'remove_tree')
                           for event in system.events if isinstance(event, tuple))


def test_stopped_service_removes_residual_local_registration_with_state():
    system = FakeSystem(answer=True)
    system.active = False
    assert main(['uninstall'], system=system) == 0
    assert not any(event[0] == 'warp-cli' for event in system.events if isinstance(event, tuple))
    assert not system.paths
    assert any('remaining local registration' in message for message in system.messages)


def test_cache_removal_failure_stops_before_runtime_and_plugin_removal():
    class RemovalFailure(FakeSystem):
        def remove_tree(self, path):
            raise PermissionError('cache could not be removed')
    system = RemovalFailure(answer=True)
    assert main(['uninstall'], system=system) == 1
    assert system.cache_dir in system.paths
    assert system.runtime_dir in system.paths
    assert system.plugin_dir in system.paths


def test_missing_runtime_directory_configuration_does_not_block_cleanup():
    system = FakeSystem(answer=True)
    system.paths.discard(system.runtime_dir)
    system.runtime_dir = None
    assert main(['uninstall'], system=system) == 0
    assert not system.paths
