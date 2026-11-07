import contextlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
import unittest

from oma_warp.cli import main


class FakeSystem:
    def __init__(self, connection='Disconnected'):
        self.outputs = {
            ('pacman', '-Qi', 'cloudflare-warp-bin'): 'Name            : cloudflare-warp-bin\nVersion         : 2026.8.2115.0-1\nInstall Date    : Thu 01 Oct 2026 12:00:00 UTC\n',
            ('systemctl', 'show', 'warp-svc', '--property=ActiveState,ActiveEnterTimestamp'): 'ActiveState=active\nActiveEnterTimestamp=Thu 01 Oct 2026 13:00:00 UTC\n',
            ('warp-cli', '-j', 'status'): json.dumps({'status': connection}),
            ('warp-cli', '-j', 'registration', 'show'): '{"id":"placeholder","account":{"type":"free"}}',
            ('warp-cli', '-j', 'settings'): '{"settings":{"operation_mode":"warp"}}',
        }
        self.runtime_dir = Path('/unused/runtime')
        self.cache_dir = Path('/unused/cache')

    def read_text(self, path):
        raise FileNotFoundError(path)

    def run(self, argv, *, timeout):
        assert timeout == 1.5
        result = self.outputs[tuple(argv)]
        if isinstance(result, Exception):
            raise result
        if isinstance(result, CompletedProcess):
            return result
        return CompletedProcess(argv, 0, result, '')

    def now(self):
        return datetime(2026, 10, 2, tzinfo=timezone.utc)

    def read_json(self, path):
        return None

    def fetch(self, *args, **kwargs):
        raise AssertionError('status must not fetch')


def status(system):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(['status', '--json'], system=system)
    assert code == 0
    return json.loads(output.getvalue())


class StatusTests(unittest.TestCase):
    def test_off_matches_shared_fixture(self):
        expected = json.loads((Path(__file__).parent / 'fixtures/off.json').read_text())
        self.assertEqual(status(FakeSystem()), expected)

    def test_connecting_matches_shared_fixture(self):
        expected = json.loads((Path(__file__).parent / 'fixtures/connecting.json').read_text())
        self.assertEqual(status(FakeSystem('Connecting')), expected)

    def test_unconfirmed_matches_shared_fixture(self):
        expected = json.loads((Path(__file__).parent / 'fixtures/unconfirmed.json').read_text())
        self.assertEqual(status(FakeSystem('Connected')), expected)

    def test_service_stopped_matches_shared_fixture(self):
        expected = json.loads((Path(__file__).parent / 'fixtures/service_stopped.json').read_text())
        system = FakeSystem()
        system.outputs[('systemctl', 'show', 'warp-svc', '--property=ActiveState,ActiveEnterTimestamp')] = 'ActiveState=inactive\nActiveEnterTimestamp=\n'
        self.assertEqual(status(system), expected)

    def test_timeouts_blank_only_their_fact_and_dependents(self):
        cases = [
            (('warp-cli', '-j', 'settings'), {}),
            (('warp-cli', '-j', 'registration', 'show'), {'registered': None}),
            (('warp-cli', '-j', 'status'), {'daemon': 'unresponsive', 'registered': None, 'connection': None}),
            (('systemctl', 'show', 'warp-svc', '--property=ActiveState,ActiveEnterTimestamp'),
             {'service': None, 'restart_needed': None, 'daemon': None, 'registered': None, 'connection': None}),
            (('pacman', '-Qi', 'cloudflare-warp-bin'),
             {'version': None, 'service': None, 'restart_needed': None, 'daemon': None, 'registered': None, 'connection': None}),
        ]
        baseline = json.loads((Path(__file__).parent / 'fixtures/off.json').read_text())['client']
        for command, changed in cases:
            with self.subTest(command=command):
                system = FakeSystem()
                system.outputs[command] = TimeoutExpired(command, 1.5)
                self.assertEqual(status(system)['client'], baseline | changed)

    def test_malformed_client_responses_still_print_partial_status(self):
        for payload in ('not json', '[]', '{"status":"NewState"}', '{"status":{}}'):
            with self.subTest(payload=payload):
                system = FakeSystem()
                system.outputs[('warp-cli', '-j', 'status')] = payload
                client = status(system)['client']
                self.assertIsNone(client['daemon'])
                self.assertIsNone(client['connection'])

    def test_stopped_service_and_missing_registration_null_dependents(self):
        system = FakeSystem()
        system.outputs[('systemctl', 'show', 'warp-svc', '--property=ActiveState,ActiveEnterTimestamp')] = 'ActiveState=inactive\n'
        client = status(system)['client']
        self.assertEqual(client['service'], 'stopped')
        self.assertIsNone(client['daemon'])
        self.assertIsNone(client['registered'])
        system = FakeSystem()
        system.outputs[('warp-cli', '-j', 'registration', 'show')] = CompletedProcess([], 1, '{"error":"MissingRegistration"}', '')
        client = status(system)['client']
        self.assertIs(client['registered'], False)
        self.assertIsNone(client['connection'])

    def test_restart_needed_compares_install_and_service_times(self):
        system = FakeSystem()
        system.outputs[('systemctl', 'show', 'warp-svc', '--property=ActiveState,ActiveEnterTimestamp')] = 'ActiveState=active\nActiveEnterTimestamp=Thu 01 Oct 2026 11:00:00 UTC\n'
        self.assertIs(status(system)['client']['restart_needed'], True)

    def test_fact_commands_run_concurrently(self):
        import threading
        import time
        class ConcurrentSystem(FakeSystem):
            barrier = threading.Barrier(5)
            def run(self, argv, *, timeout):
                self.barrier.wait(timeout=1)
                time.sleep(0.05)
                return super().run(argv, timeout=timeout)
        start = time.monotonic()
        self.assertEqual(status(ConcurrentSystem())['client']['connection'], 'disconnected')
        self.assertLess(time.monotonic() - start, 2)

    def test_executable_entry_point_supports_isolation_flags(self):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        # --help checks startup without querying the host client.
        result = subprocess.run([str(root / 'oma-warp'), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('status', result.stdout)

    def test_restart_needed_accepts_real_pacman_and_systemctl_time_formats(self):
        system = FakeSystem()
        system.outputs[('pacman', '-Qi', 'cloudflare-warp-bin')] = 'Version : 2026.8.2115.0-1\nInstall Date : Thu Oct  1 12:00:00 2026\n'
        system.outputs[('systemctl', 'show', 'warp-svc', '--property=ActiveState,ActiveEnterTimestamp')] = 'ActiveState=active\nActiveEnterTimestamp=Thu 2026-10-01 11:00:00 UTC\n'
        self.assertIs(status(system)['client']['restart_needed'], True)


def test_confirmed_missing_package_matches_fixture_and_suppresses_lower_problems():
    system = FakeSystem()
    system.outputs[('pacman', '-Qi', 'cloudflare-warp-bin')] = CompletedProcess(
        [], 1, '', "error: package 'cloudflare-warp-bin' was not found\n")
    system.outputs[('warp-cli', '-j', 'status')] = TimeoutExpired('warp-cli', 1.5)
    expected = json.loads((Path(__file__).parent / 'fixtures/not_installed.json').read_text())
    assert status(system) == expected


def test_daemon_failure_matches_fixture():
    for result in (TimeoutExpired('warp-cli', 1.5), CompletedProcess([], 1, '', 'daemon failed')):
        system = FakeSystem()
        system.outputs[('warp-cli', '-j', 'status')] = result
        expected = json.loads((Path(__file__).parent / 'fixtures/daemon_unresponsive.json').read_text())
        assert status(system) == expected


def test_missing_registration_is_a_responsive_daemon_and_matches_fixture():
    for status_result in ('{"status":"Disconnected"}', CompletedProcess([], 1, '{"error":"MissingRegistration"}', '')):
        system = FakeSystem()
        system.outputs[('warp-cli', '-j', 'status')] = status_result
        system.outputs[('warp-cli', '-j', 'registration', 'show')] = CompletedProcess([], 1, '{"error":"MissingRegistration"}', '')
        expected = json.loads((Path(__file__).parent / 'fixtures/not_registered.json').read_text())
        assert status(system) == expected


def test_unknown_facts_never_claim_missing_package_or_registration():
    for command, payloads in (
        (('pacman', '-Qi', 'cloudflare-warp-bin'), ('garbage', 'PackageMissing', TimeoutExpired('pacman', 1.5), CompletedProcess([], 1, '', 'database unavailable'))),
        (('warp-cli', '-j', 'registration', 'show'), ('{}', '{"id":false}', '{"error":"NewError"}', TimeoutExpired('warp-cli', 1.5))),
    ):
        for payload in payloads:
            system = FakeSystem()
            system.outputs[command] = payload
            doc = status(system)
            assert doc['problems'] == []
            assert doc['client']['registered'] is None


def test_malformed_package_version_does_not_claim_installed_or_missing():
    for version in ('garbage', 'false', '2026.8.2115.0-1\nVersion : nonsense'):
        system = FakeSystem()
        system.outputs[('pacman', '-Qi', 'cloudflare-warp-bin')] = 'Version : ' + version
        doc = status(system)
        assert doc['client']['version'] is None
        assert doc['client']['service'] is None
        assert doc['problems'] == []


def test_hanging_sources_use_real_subprocess_deadlines_without_blanking_unrelated_facts():
    import sys
    import time
    from oma_warp.system import System

    commands = list(FakeSystem().outputs)
    baseline = status(FakeSystem())['client']
    changes = (
        dict.fromkeys(baseline),
        {'service': None, 'restart_needed': None, 'daemon': None, 'registered': None, 'connection': None},
        {'daemon': 'unresponsive', 'registered': None, 'connection': None},
        {'registered': None},
        {},
    )
    for command, changed in zip(commands, changes):
        class HangingSystem(FakeSystem):
            def run(self, argv, *, timeout):
                if tuple(argv) == command:
                    # The actual System subprocess boundary enforces the deadline;
                    # this isolated sleeper never queries or changes host WARP.
                    return System.run(self, [sys.executable, '-I', '-c', 'import time; time.sleep(30)'], timeout=timeout)
                return super().run(argv, timeout=timeout)
        started = time.monotonic()
        doc = status(HangingSystem())
        assert time.monotonic() - started < 2
        assert doc['client'] == baseline | changed
        if command == commands[0]:
            assert doc['problems'] == []
