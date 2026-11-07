import contextlib
import io
from subprocess import CompletedProcess, TimeoutExpired
import unittest

from oma_warp.cli import main


class ScriptedSystem:
    """Only the system boundary is faked: a scripted command runner."""

    def __init__(self, result=None):
        self.result = result if result is not None else CompletedProcess([], 0, 'Success\n', '')
        self.calls = []
        self.runtime_dir = None

    def run(self, argv, *, timeout):
        self.calls.append((list(argv), timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def now(self):
        raise AssertionError('connect/disconnect need no clock')

    def fetch(self, *args, **kwargs):
        raise AssertionError('connect/disconnect must not fetch')


def run(argv, system):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv, system=system)
    return code, out.getvalue(), err.getvalue()


class ConnectionTests(unittest.TestCase):
    def test_switch_commands_ask_warp_cli_without_root(self):
        for command in ('connect', 'disconnect'):
            with self.subTest(command=command):
                system = ScriptedSystem()
                code, out, _ = run([command], system)
                self.assertEqual(code, 0)
                self.assertEqual(out, '')
                self.assertEqual(len(system.calls), 1)
                argv, timeout = system.calls[0]
                self.assertEqual(argv, ['warp-cli', command])
                self.assertLessEqual(timeout, 10)

    def test_a_failed_switch_exits_non_zero_and_says_why(self):
        cases = [
            (CompletedProcess([], 1, '', 'Error: daemon not ready\n'), 'daemon not ready'),
            (TimeoutExpired(['warp-cli', 'connect'], 10), 'timed out'),
            (FileNotFoundError(2, 'No such file or directory'), 'No such file or directory'),
        ]
        for result, reason in cases:
            with self.subTest(reason=reason):
                code, out, err = run(['connect'], ScriptedSystem(result))
                self.assertNotEqual(code, 0)
                self.assertEqual(out, '')
                self.assertIn(reason, err)

    def test_reconnect_disconnects_before_connecting_without_root(self):
        system = ScriptedSystem()
        code, out, err = run(['reconnect'], system)
        self.assertEqual((code, out, err), (0, '', ''))
        self.assertEqual([argv for argv, _ in system.calls],
                         [['warp-cli', 'disconnect'], ['warp-cli', 'connect']])

    def test_reconnect_stops_when_disconnect_fails(self):
        system = ScriptedSystem(CompletedProcess([], 1, '', 'disconnect failed'))
        code, _, err = run(['reconnect'], system)
        self.assertEqual(code, 1)
        self.assertIn('disconnect failed', err)
        self.assertEqual([argv for argv, _ in system.calls], [['warp-cli', 'disconnect']])
