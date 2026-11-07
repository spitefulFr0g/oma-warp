"""Trace scenarios at the backend entry point; only System is faked."""
import contextlib
import io
import json
from pathlib import Path
import unittest

from oma_warp.cli import main
from test_status import FakeSystem
from test_contract import assert_contract


class ProbeSystem(FakeSystem):
    def __init__(self):
        super().__init__('Connected')
        self.files = {}
        self.body = b'ip=203.0.113.7\ncolo=XXX\nloc=XX\nwarp=on\n'
        self.fetches = []

    def monotonic(self):
        import time
        return time.monotonic()

    def run(self, argv, *, timeout):
        assert timeout in (0.2, 1.5)
        return super().run(argv, timeout=1.5)

    def fetch(self, url, *, timeout, limit):
        self.fetches.append((url, timeout))
        if isinstance(self.body, Exception):
            raise self.body
        return self.body

    def read_text(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def atomic_write(self, path, text):
        self.files[path] = text

    def remove_file(self, path):
        self.files.pop(path, None)


def status(system, probe=False):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(['status', '--json'] + (['--probe'] if probe else []), system=system)
    assert code == 0
    return json.loads(output.getvalue())


class ProbeTests(unittest.TestCase):
    def test_through_cloudflare_and_plain_status_reuses_matching_probe(self):
        system = ProbeSystem()
        doc = status(system, True)
        self.assertEqual(doc['probe'], {
            'checked_at': '2026-10-02T00:00:00Z', 'trace': 'through',
            'ip': '203.0.113.7', 'colo': 'XXX', 'country': 'XX', 'dns': None})
        self.assertEqual(doc['problems'], [])
        self.assertEqual(status(system)['probe'], doc['probe'])
        self.assertEqual(system.fetches, [('https://www.cloudflare.com/cdn-cgi/trace', 4)])
        assert_contract(self, doc)

    def test_outside_is_nonblocking_only_in_warp_mode(self):
        for mode, problems in [('warp', [{'code': 'not_through_cloudflare', 'fix': 'reconnect', 'blocking': False}]),
                               ('doh', []), ('warp+doh', [])]:
            with self.subTest(mode=mode):
                system = ProbeSystem()
                system.body = system.body.replace(b'warp=on', b'warp=off')
                system.outputs[('warp-cli', '-j', 'settings')] = json.dumps({'settings': {'operation_mode': mode}})
                doc = status(system, True)
                self.assertEqual(doc['probe']['trace'], 'outside')
                self.assertEqual(doc['probe']['ip'], '203.0.113.7')
                self.assertEqual(doc['problems'], problems)

    def test_failed_or_malformed_trace_has_no_ip_or_problem(self):
        for body in (OSError('offline'), b'bad', b'ip=invalid\nwarp=on',
                     b'ip=203.0.113.7\nwarp=unexpected\ncolo=XXX\nloc=XX',
                     b'ip=203.0.113.7\nwarp=on\ncolo=XXX'):
            with self.subTest(body=body):
                system = ProbeSystem()
                system.body = body
                doc = status(system, True)
                self.assertEqual(doc['probe']['trace'], 'failed')
                self.assertIsNone(doc['probe']['ip'])
                self.assertEqual(doc['problems'], [])

    def test_connection_change_or_restart_discards_probe_and_removes_cache(self):
        for command, changed in [
            (('warp-cli', '-j', 'status'), '{"status":"Disconnected"}'),
            (('systemctl', 'show', 'warp-svc', '--property=ActiveState,ActiveEnterTimestamp'),
             'ActiveState=active\nActiveEnterTimestamp=Thu 01 Oct 2026 14:00:00 UTC\n')]:
            with self.subTest(command=command):
                system = ProbeSystem()
                original = system.outputs[command]
                self.assertIsNotNone(status(system, True)['probe'])
                system.outputs[command] = changed
                self.assertIsNone(status(system)['probe'])
                system.outputs[command] = original
                self.assertIsNone(status(system)['probe'])

    def test_state_change_during_trace_never_publishes_stale_confirmation(self):
        class ChangingSystem(ProbeSystem):
            def fetch(self, *args, **kwargs):
                self.outputs[('warp-cli', '-j', 'status')] = '{"status":"Disconnected"}'
                return super().fetch(*args, **kwargs)
        system = ChangingSystem()
        self.assertIsNone(status(system, True)['probe'])
        system.outputs[('warp-cli', '-j', 'status')] = '{"status":"Connected"}'
        self.assertIsNone(status(system)['probe'])

    def test_probe_has_total_deadline_even_when_trace_does_not_finish(self):
        import time
        class SlowSystem(ProbeSystem):
            def fetch(self, *args, **kwargs):
                time.sleep(5.5)
                return super().fetch(*args, **kwargs)
        started = time.monotonic()
        doc = status(SlowSystem(), True)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(doc['probe']['trace'], 'failed')
        self.assertIsNone(doc['probe']['ip'])

    def test_backend_matches_new_shared_fixtures(self):
        for name, warp in [('on', b'plus'), ('outside', b'off'), ('trace_failed', None), ('dropped', b'on')]:
            with self.subTest(fixture=name):
                system = ProbeSystem()
                system.body = system.body.replace(b'warp=on', b'warp=' + warp) if warp else b'incomplete'
                doc = status(system, True)
                if name == 'dropped':
                    system.outputs[('warp-cli', '-j', 'status')] = '{"status":"Disconnected"}'
                    doc = status(system)
                expected = json.loads((Path(__file__).parent / 'fixtures' / (name + '.json')).read_text())
                self.assertEqual(doc, expected)
                assert_contract(self, doc)

    def test_blocking_problem_is_alone_even_when_trace_is_outside(self):
        system = ProbeSystem()
        system.body = system.body.replace(b'warp=on', b'warp=off')
        system.outputs[('systemctl', 'show', 'warp-svc', '--property=ActiveState,ActiveEnterTimestamp')] = 'ActiveState=inactive\n'
        doc = status(system, True)
        self.assertEqual(doc['problems'], [{'code': 'service_stopped', 'fix': 'start', 'blocking': True}])
        assert_contract(self, doc)

    def test_reconnect_invalidates_confirmation_even_if_next_poll_is_connected(self):
        from subprocess import CompletedProcess
        class SwitchingSystem(ProbeSystem):
            def run(self, argv, *, timeout):
                if argv in (['warp-cli', 'disconnect'], ['warp-cli', 'connect']):
                    return CompletedProcess(argv, 0, '', '')
                return super().run(argv, timeout=timeout)
        system = SwitchingSystem()
        self.assertIsNotNone(status(system, True)['probe'])
        self.assertEqual(main(['reconnect'], system=system), 0)
        self.assertIsNone(status(system)['probe'])

    def test_trace_ipv6_and_unavailable_runtime_still_report_without_caching(self):
        system = ProbeSystem()
        system.runtime_dir = None
        system.body = system.body.replace(b'203.0.113.7', b'2001:db8::7')
        doc = status(system, True)
        self.assertEqual(doc['probe']['ip'], '2001:db8::7')
        self.assertIsNone(status(system)['probe'])
        assert_contract(self, doc)

    def test_probe_during_service_restart_cannot_be_relabelled_as_current(self):
        class RestartingSystem(ProbeSystem):
            def fetch(self, *args, **kwargs):
                self.outputs[('systemctl', 'show', 'warp-svc', '--property=ActiveState,ActiveEnterTimestamp')] = (
                    'ActiveState=active\nActiveEnterTimestamp=Thu 01 Oct 2026 14:00:00 UTC\n')
                return super().fetch(*args, **kwargs)
        system = RestartingSystem()
        self.assertIsNone(status(system, True)['probe'])
        self.assertIsNone(status(system)['probe'])
