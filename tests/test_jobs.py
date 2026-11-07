"""Jobs through the same CLI boundary the floating terminal uses."""
import json
from pathlib import Path
from subprocess import CompletedProcess

from oma_warp.cli import main
from test_status import FakeSystem, status


class JobSystem(FakeSystem):
    def __init__(self):
        super().__init__()
        self.files = {}
        self.identities = {123: '456'}
        self.current_pid = 123
        self.messages = []
        self.commands = []
        self.during_terminal = lambda: None
        self.terminal_result = CompletedProcess([], 0)
        self.locked = False

    def read_text(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def atomic_write(self, path, text):
        self.files[path] = text

    def remove_file(self, path):
        self.files.pop(path, None)

    def exclusive_lock(self, path):
        from contextlib import contextmanager
        @contextmanager
        def acquire():
            acquired = not self.locked
            if acquired:
                self.locked = True
            try:
                yield acquired
            finally:
                if acquired:
                    self.locked = False
        return acquire()

    def process_start_time(self, pid):
        return self.identities.get(pid)

    def write(self, message):
        self.messages.append(message)

    def run_terminal(self, argv):
        self.commands.append(argv)
        self.during_terminal()
        if isinstance(self.terminal_result, BaseException):
            raise self.terminal_result
        return self.terminal_result


def test_start_is_visible_only_while_running_and_matches_job_fixture():
    system = JobSystem()
    def during():
        expected = json.loads((Path(__file__).parent / 'fixtures/job.json').read_text())
        assert status(system) == expected
        record = json.loads(system.files[system.runtime_dir / 'job.json'])
        assert record == {'job_id': 'example-job', 'action': 'start',
                          'started_at': '2026-10-02T00:00:00Z', 'pid': 123,
                          'process_start_time': '456'}
    system.during_terminal = during
    assert main(['start', '--job-id', 'example-job'], system=system) == 0
    assert system.commands == [['sudo', 'systemctl', 'enable', '--now', 'warp-svc']]
    assert status(system)['job'] is None
    assert system.runtime_dir / 'job.json' not in system.files
    assert any('started' in line.lower() for line in system.messages)


def test_interrupted_publication_cleans_the_record_before_releasing_ownership():
    class InterruptedSystem(JobSystem):
        def atomic_write(self, path, text):
            super().atomic_write(path, text)
            raise KeyboardInterrupt()
    system = InterruptedSystem()
    assert main(['start', '--job-id', 'interrupted'], system=system) == 130
    assert status(system)['job'] is None
    assert system.runtime_dir / 'job.json' not in system.files
    assert not system.locked
    assert system.commands == []


def record(**changes):
    return json.dumps({'job_id': 'earlier-job', 'action': 'update',
                       'started_at': '2026-10-02T00:00:00Z', 'pid': 999,
                       'process_start_time': '888'} | changes)


def test_live_job_is_refused_even_when_no_runner_lock_is_held():
    system = JobSystem()
    system.files[system.runtime_dir / 'job.json'] = record()
    system.identities[999] = '888'
    assert main(['start', '--job-id', 'second'], system=system) == 1
    assert system.commands == []
    assert status(system)['job'] == {'action': 'update', 'started_at': '2026-10-02T00:00:00Z'}
    assert any('another Job' in line for line in system.messages)


def test_dead_reused_and_untrusted_records_are_hidden_and_replaceable():
    cases = [(record(), None), (record(), 'different-start-time'),
             ('{', None), ('[]', None), ('null', None),
             (record(pid=True), None), (record(process_start_time=None), None),
             (record(action='uninstall'), None), (record(started_at='bad'), None),
             (record(started_at='2026-10-02T00:00:00'), None),
             (record(job_id=''), None)]
    for text, identity in cases:
        system = JobSystem()
        system.files[system.runtime_dir / 'job.json'] = text
        if identity is not None:
            system.identities[999] = identity
        assert status(system)['job'] is None
        assert main(['start', '--job-id', 'replacement'], system=system) == 0
        assert system.runtime_dir / 'job.json' not in system.files


def test_contender_is_refused_before_record_publication_and_during_terminal():
    class RacingSystem(JobSystem):
        def atomic_write(self, path, text):
            # A competing CLI process arrives after lock acquisition, before
            # job.json exists. Both processes share the fake OS boundary.
            commands_before = list(self.commands)
            assert main(['start', '--job-id', 'racing'], system=self) == 1
            assert self.commands == commands_before
            super().atomic_write(path, text)
    system = RacingSystem()
    def during():
        assert main(['start', '--job-id', 'second'], system=system) == 1
        assert len(system.commands) == 1
    system.during_terminal = during
    assert main(['start', '--job-id', 'winner'], system=system) == 0
    assert not system.locked
    # Ownership is reusable, including after the contender was refused.
    system.during_terminal = lambda: None
    assert main(['start', '--job-id', 'later'], system=system) == 0
    assert len(system.commands) == 2


def test_failed_and_interrupted_terminal_commands_leave_no_job():
    from subprocess import TimeoutExpired
    cases = [(CompletedProcess([], 5), 5), (FileNotFoundError('missing sudo'), 1),
             (TimeoutExpired('sudo', 1), 1), (KeyboardInterrupt(), 130)]
    for result, expected_code in cases:
        system = JobSystem()
        system.terminal_result = result
        assert main(['start', '--job-id', 'failure'], system=system) == expected_code
        assert status(system)['job'] is None
        assert system.runtime_dir / 'job.json' not in system.files
        assert not system.locked
        assert system.messages


def test_start_refuses_without_runtime_or_process_identity_or_job_id():
    for missing in ('runtime', 'identity', 'job id'):
        system = JobSystem()
        if missing == 'runtime':
            system.runtime_dir = None
        if missing == 'identity':
            system.identities.clear()
        assert main(['start', '--job-id', '' if missing == 'job id' else 'example'], system=system) == 1
        assert system.commands == []
        assert not system.files


def test_unexpected_operation_error_still_cleans_record_and_releases_lock():
    import pytest
    system = JobSystem()
    system.terminal_result = RuntimeError('unexpected operation failure')
    with pytest.raises(RuntimeError, match='unexpected operation failure'):
        main(['start', '--job-id', 'failure'], system=system)
    assert system.runtime_dir / 'job.json' not in system.files
    assert not system.locked


def test_independent_processes_share_exclusive_ownership(tmp_path):
    """Exercise CLI contention with real kernel locks in an isolated runtime.

    Only System is substituted. Commands remain scripted; no host WARP facts
    are read or changed. The two Events pause at external-effect boundaries.
    """
    import multiprocessing
    from oma_warp.system import System

    context = multiprocessing.get_context('fork')
    publishing, publish = context.Event(), context.Event()
    terminal, finish = context.Event(), context.Event()

    class IsolatedSystem(System):
        @property
        def runtime_dir(self):
            return tmp_path

        def run(self, argv, *, timeout):
            return FakeSystem().run(argv, timeout=timeout)

        def now(self):
            return FakeSystem().now()

        def write(self, message):
            pass

    class PausedSystem(IsolatedSystem):
        def atomic_write(self, path, text):
            publishing.set()
            assert publish.wait(5)
            super().atomic_write(path, text)

        def run_terminal(self, argv):
            assert argv == ['sudo', 'systemctl', 'enable', '--now', 'warp-svc']
            terminal.set()
            assert finish.wait(5)
            return CompletedProcess(argv, 0)

    def child():
        raise SystemExit(main(['start', '--job-id', 'child'], system=PausedSystem()))

    process = context.Process(target=child)
    process.start()
    try:
        assert publishing.wait(5)
        observer = IsolatedSystem()
        assert status(observer)['job'] is None
        assert main(['start', '--job-id', 'contender'], system=observer) == 1
        publish.set()
        assert terminal.wait(5)
        assert status(observer)['job'] == {'action': 'start', 'started_at': '2026-10-02T00:00:00Z'}
        assert main(['start', '--job-id', 'contender'], system=observer) == 1
        finish.set()
        process.join(5)
        assert process.exitcode == 0
        assert status(observer)['job'] is None
        # No temporary files or record survive; the lock inode is retained.
        assert sorted(path.name for path in tmp_path.iterdir()) == ['job.lock']
    finally:
        publish.set()
        finish.set()
        if process.is_alive():
            process.terminate()
        process.join(5)


def test_register_inherits_terminal_and_reports_live_job_until_completion():
    system = JobSystem()
    def during():
        assert status(system)['job'] == {'action': 'register', 'started_at': '2026-10-02T00:00:00Z'}
        assert main(['start', '--job-id', 'contender'], system=system) == 1
    system.during_terminal = during
    assert main(['register', '--job-id', 'registration'], system=system) == 0
    assert system.commands == [['warp-cli', 'registration', 'new']]
    assert status(system)['job'] is None
    assert system.runtime_dir / 'job.json' not in system.files
    assert any('registered' in message.lower() for message in system.messages)


def test_register_failure_interruption_and_contention_use_shared_job_cleanup():
    for result, expected in ((CompletedProcess([], 7), 7),
                             (FileNotFoundError('missing warp-cli'), 1),
                             (KeyboardInterrupt(), 130)):
        system = JobSystem()
        system.terminal_result = result
        assert main(['register', '--job-id', 'failure'], system=system) == expected
        assert status(system)['job'] is None
        assert system.runtime_dir / 'job.json' not in system.files
        assert not system.locked
        assert system.messages
    system = JobSystem()
    system.locked = True
    assert main(['register', '--job-id', 'contender'], system=system) == 1
    assert system.commands == []
