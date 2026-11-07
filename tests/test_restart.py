"""Restart behavior through the terminal and status CLI seams only."""
import json
from subprocess import CompletedProcess

from oma_warp.cli import main
from test_jobs import JobSystem
from test_status import status


class RestartSystem(JobSystem):
    def __init__(self, prior='Connected', restored='Connected', restore_after=2):
        super().__init__()
        self.outputs[('warp-cli', '-j', 'status')] = json.dumps({'status': prior})
        self.restored = restored
        self.restore_after = restore_after
        self.elapsed = 0
        self.restarted = False
        self.waits = []
        self.reads = []

    def monotonic(self):
        return self.elapsed

    def wait(self, seconds):
        assert seconds > 0
        assert status(self)['job'] == {'action': 'restart', 'started_at': '2026-10-02T00:00:00Z'}
        self.waits.append(seconds)
        self.elapsed += seconds
        if self.elapsed >= self.restore_after:
            self.outputs[('warp-cli', '-j', 'status')] = json.dumps({'status': self.restored})

    def run(self, argv, *, timeout):
        self.reads.append((argv, timeout))
        if argv == ['warp-cli', '-j', 'status']:
            assert 0 < timeout <= 1.5
            result = self.outputs[tuple(argv)]
            if isinstance(result, BaseException):
                raise result
            return result if isinstance(result, CompletedProcess) else CompletedProcess(argv, 0, result, '')
        return super().run(argv, timeout=timeout)

    def run_terminal(self, argv):
        result = super().run_terminal(argv)
        if argv == ['sudo', 'systemctl', 'restart', 'warp-svc']:
            self.restarted = True
            self.outputs[('warp-cli', '-j', 'status')] = '{"status":"Connecting"}'
        return result


def test_restart_waits_for_automatic_restore_with_live_job_and_no_connect():
    system = RestartSystem()
    assert main(['restart', '--job-id', 'restore'], system=system) == 0
    assert system.commands == [['sudo', 'systemctl', 'restart', 'warp-svc']]
    assert 2 <= system.elapsed <= 15
    assert system.messages[-1] == 'Connected again'
    assert status(system)['job'] is None
    assert not system.locked


def test_restart_connects_once_only_after_automatic_restore_window():
    class FallbackSystem(RestartSystem):
        def run(self, argv, *, timeout):
            if argv == ['warp-cli', 'connect']:
                assert self.elapsed == 15
                self.commands.append(argv)
                self.outputs[('warp-cli', '-j', 'status')] = '{"status":"Connected"}'
                return CompletedProcess(argv, 0, '', '')
            return super().run(argv, timeout=timeout)
    system = FallbackSystem(restored='Disconnected')
    assert main(['restart', '--job-id', 'fallback'], system=system) == 0
    assert system.commands == [['sudo', 'systemctl', 'restart', 'warp-svc'], ['warp-cli', 'connect']]
    assert system.messages[-1] == 'Connected again'
    assert status(system)['job'] is None


def test_restore_at_end_of_window_does_not_issue_unnecessary_connect():
    system = RestartSystem(restore_after=15)
    assert main(['restart', '--job-id', 'last-moment'], system=system) == 0
    assert system.commands == [['sudo', 'systemctl', 'restart', 'warp-svc']]
    assert system.messages[-1] == 'Connected again'


def test_disconnected_and_unknown_prior_states_never_connect():
    from subprocess import TimeoutExpired
    for prior in ('Disconnected', 'Connecting', 'NewState', None):
        for restored in ('Disconnected', 'Connected', 'Connecting'):
            system = RestartSystem(prior=prior, restored=restored)
            assert main(['restart', '--job-id', 'no-connect'], system=system) == 0
            assert system.commands == [['sudo', 'systemctl', 'restart', 'warp-svc']]
            assert system.messages[-1] in ('Connected again', 'WARP did not reconnect')
            assert system.elapsed <= 15
            assert status(system)['job'] is None
    for unknown in (TimeoutExpired('warp-cli', 1.5), FileNotFoundError('warp-cli'),
                    CompletedProcess([], 1, '', 'unresponsive'), 'invalid json'):
        system = RestartSystem(restored='Disconnected')
        system.outputs[('warp-cli', '-j', 'status')] = unknown
        assert main(['restart', '--job-id', 'unknown'], system=system) == 0
        assert system.commands == [['sudo', 'systemctl', 'restart', 'warp-svc']]
        assert system.messages[-1] == 'WARP did not reconnect'


def test_failed_fallback_never_retries_and_reports_observed_outcome():
    from subprocess import TimeoutExpired
    for result in (CompletedProcess([], 4, '', 'failure'), TimeoutExpired('connect', 10),
                   FileNotFoundError('warp-cli'), CompletedProcess([], 0, '', '')):
        class FailedFallback(RestartSystem):
            def run(self, argv, *, timeout):
                if argv == ['warp-cli', 'connect']:
                    self.commands.append(argv)
                    assert self.elapsed == 15
                    if isinstance(result, BaseException):
                        raise result
                    return result
                return super().run(argv, timeout=timeout)
        system = FailedFallback(restored='Disconnected')
        assert main(['restart', '--job-id', 'no-retry'], system=system) == 1
        assert system.commands == [['sudo', 'systemctl', 'restart', 'warp-svc'], ['warp-cli', 'connect']]
        assert system.messages[-1] == 'WARP did not reconnect'
        assert status(system)['job'] is None
        assert not system.locked


def test_restart_failure_interruption_and_contention_clean_up_without_connect():
    for result, expected in ((CompletedProcess([], 7), 7),
                             (FileNotFoundError('sudo'), 1), (KeyboardInterrupt(), 130)):
        system = RestartSystem()
        system.terminal_result = result
        assert main(['restart', '--job-id', 'failed'], system=system) == expected
        assert system.commands == [['sudo', 'systemctl', 'restart', 'warp-svc']]
        assert system.waits == []
        assert status(system)['job'] is None
        assert not system.locked
    system = RestartSystem()
    system.locked = True
    assert main(['restart', '--job-id', 'contender'], system=system) == 1
    assert system.commands == []
    assert system.reads == []


def test_interrupt_during_restore_wait_releases_job():
    class InterruptedWait(RestartSystem):
        def wait(self, seconds):
            super().wait(seconds)
            raise KeyboardInterrupt()
    system = InterruptedWait()
    assert main(['restart', '--job-id', 'interrupt'], system=system) == 130
    assert status(system)['job'] is None
    assert not system.locked


def test_restart_discards_probe_from_previous_service_lifetime():
    from pathlib import Path
    class ImmediateRestore(RestartSystem):
        def run_terminal(self, argv):
            result = super().run_terminal(argv)
            self.outputs[('warp-cli', '-j', 'status')] = '{"status":"Connected"}'
            return result
    system = ImmediateRestore()
    probe = json.loads((Path(__file__).parent / 'fixtures/on.json').read_text())['probe']
    system.files[system.runtime_dir / 'probe.json'] = json.dumps({
        'tag': {'connection': 'connected', 'service_started': 'Thu 01 Oct 2026 13:00:00 UTC'},
        'probe': probe,
    })
    assert status(system)['probe'] == probe
    assert main(['restart', '--job-id', 'fresh-service'], system=system) == 0
    assert status(system)['probe'] is None


def test_single_connect_fallback_observes_asynchronous_connection():
    class AsyncFallback(RestartSystem):
        def run(self, argv, *, timeout):
            if argv == ['warp-cli', 'connect']:
                self.commands.append(argv)
                self.outputs[('warp-cli', '-j', 'status')] = '{"status":"Connecting"}'
                self.restored = 'Connected'
                self.restore_after = self.elapsed + 2
                return CompletedProcess(argv, 0, '', '')
            return super().run(argv, timeout=timeout)
    system = AsyncFallback(restored='Disconnected')
    assert main(['restart', '--job-id', 'async-fallback'], system=system) == 0
    assert system.commands == [['sudo', 'systemctl', 'restart', 'warp-svc'], ['warp-cli', 'connect']]
    assert system.elapsed <= 20
    assert system.messages[-1] == 'Connected again'
