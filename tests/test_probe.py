"""Trace scenarios at the backend entry point; only System is faked."""
import contextlib
import io
import json
from pathlib import Path
from subprocess import CompletedProcess
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
        self.outputs[('timeout', '4', 'getent', 'ahostsv4', 'connectivity-check.warp-svc')] = OSError('unavailable')
        self.outputs[('resolvectl', 'domain')] = OSError('unavailable')

    def monotonic(self):
        import time
        return time.monotonic()

    def run(self, argv, *, timeout):
        assert timeout in (0.2, 1.5, 4)
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


class DnsSystem(ProbeSystem):
    def __init__(self):
        super().__init__()
        self.outputs[('timeout', '4', 'getent', 'ahostsv4', 'connectivity-check.warp-svc')] = (
            '127.0.2.2 STREAM connectivity-check.warp-svc\n'
            '127.0.2.3 DGRAM\n127.0.2.2 RAW\n')
        self.outputs[('resolvectl', 'domain')] = 'Global:\nLink 7 (CloudflareWARP): ~.\nLink 2 (eth0): example.test\n'

    def run(self, argv, *, timeout):
        if argv[0] in ('timeout', 'resolvectl'):
            assert 0 < timeout <= 4
            return FakeSystem.run(self, argv, timeout=1.5)
        return super().run(argv, timeout=timeout)


class DnsTests(unittest.TestCase):
    def test_warp_dns_answers_and_exclusive_domain_claim_are_ok(self):
        system = DnsSystem()
        doc = status(system, True)
        self.assertEqual(doc['probe']['dns'], 'ok')
        self.assertEqual(doc['problems'], [])
        self.assertEqual(status(system)['probe']['dns'], 'ok')
        assert_contract(self, doc)

    def test_dns_problems_follow_routing_and_have_the_specified_fixes(self):
        from subprocess import TimeoutExpired
        for verdict, answer, domain, fix in (
            ('broken', TimeoutExpired('getent', 4), None, None),
            ('broken', CompletedProcess([], 124, '', ''), None, None),
            ('bypassed', CompletedProcess([], 2, '', ''), None, 'reconnect'),
            ('shared', None, 'Global: ~.\nLink 7 (CloudflareWARP): ~.\n', None),
            ('shared', None, 'Global:\nLink 7 (CloudflareWARP): ~.\nLink 8 (tailscale0): ~.\n', None),
        ):
            with self.subTest(verdict=verdict, answer=answer, domain=domain):
                system = DnsSystem()
                if answer is not None:
                    system.outputs[('timeout', '4', 'getent', 'ahostsv4', 'connectivity-check.warp-svc')] = answer
                if domain is not None:
                    system.outputs[('resolvectl', 'domain')] = domain
                system.body = system.body.replace(b'warp=on', b'warp=off')
                doc = status(system, True)
                self.assertEqual(doc['probe']['dns'], verdict)
                self.assertEqual(doc['problems'], [
                    {'code': 'not_through_cloudflare', 'fix': 'reconnect', 'blocking': False},
                    {'code': 'dns_' + verdict, 'fix': fix, 'blocking': False}])
                assert_contract(self, doc)

    def test_unexpected_dns_facts_stay_unknown(self):
        from subprocess import TimeoutExpired
        lookup = ('timeout', '4', 'getent', 'ahostsv4', 'connectivity-check.warp-svc')
        for command, payload in (
            (lookup, ''), (lookup, '203.0.113.7 STREAM connectivity-check.warp-svc\n'),
            (lookup, '127.0.2.2 nonsense\n'), (lookup, '127.0.2.2 STREAM unexpected\n'),
            (lookup, '127.0.2.2 STREAM\ngarbage\n'),
            (lookup, CompletedProcess([], 1, '', 'unavailable')),
            (lookup, OSError('missing tool')),
            (('resolvectl', 'domain'), 'garbage'),
            (('resolvectl', 'domain'), 'Global:\nLink 7 (CloudflareWARP):\n'),
            (('resolvectl', 'domain'), 'Link 7 (CloudflareWARP): ~.\nmalformed'),
            (('resolvectl', 'domain'), 'Link 7 (CloudflareWARP): ~.\nLink 7 (CloudflareWARP): ~.\n'),
            (('resolvectl', 'domain'), TimeoutExpired('resolvectl', 4)),
        ):
            with self.subTest(command=command, payload=payload):
                system = DnsSystem()
                system.outputs[command] = payload
                doc = status(system, True)
                self.assertIsNone(doc['probe']['dns'])
                self.assertEqual(doc['problems'], [])

    def test_dns_is_not_queried_without_connected_warp_mode_and_cache_is_sanitized(self):
        lookup = ('timeout', '4', 'getent', 'ahostsv4', 'connectivity-check.warp-svc')
        for command, payload in (
            (('warp-cli', '-j', 'status'), '{"status":"Disconnected"}'),
            (('warp-cli', '-j', 'status'), '{"status":"Connecting"}'),
            (('warp-cli', '-j', 'settings'), '{"settings":{"operation_mode":"doh"}}'),
            (('warp-cli', '-j', 'settings'), '{"settings":{"operation_mode":"warp+doh"}}'),
            (('warp-cli', '-j', 'settings'), '{"settings":[]}'),
            (('warp-cli', '-j', 'settings'), '{"settings":{"operation_mode":false}}'),
        ):
            with self.subTest(payload=payload):
                system = DnsSystem()
                self.assertEqual(status(system, True)['probe']['dns'], 'ok')
                system.outputs[command] = payload
                system.outputs[lookup] = AssertionError('DNS must not be queried')
                system.outputs[('resolvectl', 'domain')] = AssertionError('DNS must not be queried')
                cached = status(system)['probe']
                self.assertTrue(cached is None or cached['dns'] is None)
                self.assertIsNone(status(system, True)['probe']['dns'])

    def test_dns_and_trace_run_together_and_omarchy_dns_over_tls_is_not_a_problem(self):
        import threading
        class ConcurrentSystem(DnsSystem):
            barrier = threading.Barrier(3)
            def fetch(self, *args, **kwargs):
                self.barrier.wait(timeout=1)
                return super().fetch(*args, **kwargs)
            def run(self, argv, *, timeout):
                if argv[0] in ('timeout', 'resolvectl'):
                    self.barrier.wait(timeout=1)
                return super().run(argv, timeout=timeout)
            def read_text(self, path):
                if str(path).endswith('resolved.conf'):
                    return '# Managed by omarchy-dns\nDNSOverTLS=yes\n'
                return super().read_text(path)
        doc = status(ConcurrentSystem(), True)
        self.assertEqual(doc['probe']['dns'], 'ok')
        self.assertEqual(doc['problems'], [])

    def test_dns_has_total_deadline_and_late_workers_cannot_publish(self):
        import threading
        import time
        class SlowSystem(DnsSystem):
            release = threading.Event()
            finished = threading.Event()
            def run(self, argv, *, timeout):
                if argv[0] == 'timeout':
                    self.release.wait(timeout=8)
                    self.finished.set()
                return super().run(argv, timeout=timeout)
        system = SlowSystem()
        started = time.monotonic()
        doc = status(system, True)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(doc['probe']['dns'], 'broken')
        self.assertEqual(doc['probe']['trace'], 'through')
        system.outputs[('warp-cli', '-j', 'status')] = '{"status":"Disconnected"}'
        self.assertIsNone(status(system)['probe'])
        system.release.set()
        self.assertTrue(system.finished.wait(timeout=1))
        system.outputs[('warp-cli', '-j', 'status')] = '{"status":"Connected"}'
        self.assertIsNone(status(system)['probe'])

    def test_blocking_problem_is_alone_with_dns_and_routing_failures(self):
        system = DnsSystem()
        system.body = system.body.replace(b'warp=on', b'warp=off')
        system.outputs[('timeout', '4', 'getent', 'ahostsv4', 'connectivity-check.warp-svc')] = CompletedProcess([], 2, '', '')
        system.outputs[('warp-cli', '-j', 'registration', 'show')] = CompletedProcess([], 1, '{"error":"MissingRegistration"}', '')
        doc = status(system, True)
        self.assertEqual(doc['problems'], [{'code': 'not_registered', 'fix': 'register', 'blocking': True}])
        self.assertIsNone(doc['probe'])
        assert_contract(self, doc)


    def test_resolver_inspection_deadline_does_not_claim_dns_lookup_failed(self):
        import threading
        class SlowDomains(DnsSystem):
            release = threading.Event()
            def run(self, argv, *, timeout):
                if argv[0] == 'resolvectl':
                    self.release.wait(timeout=8)
                return super().run(argv, timeout=timeout)
        system = SlowDomains()
        try:
            doc = status(system, True)
            self.assertIsNone(doc['probe']['dns'])
            self.assertEqual(doc['problems'], [])
        finally:
            system.release.set()

    def test_backend_reproduces_dns_and_multi_fixtures(self):
        for name, verdict in (('dns_broken', 'broken'), ('dns_bypassed', 'bypassed'),
                              ('dns_shared', 'shared'), ('multi', 'bypassed')):
            with self.subTest(fixture=name):
                system = DnsSystem()
                lookup = ('timeout', '4', 'getent', 'ahostsv4', 'connectivity-check.warp-svc')
                if verdict == 'broken':
                    system.outputs[lookup] = CompletedProcess([], 124, '', '')
                elif verdict == 'bypassed':
                    system.outputs[lookup] = CompletedProcess([], 2, '', '')
                else:
                    system.outputs[('resolvectl', 'domain')] += 'Link 8 (tailscale0): ~.\n'
                if name == 'multi':
                    system.body = system.body.replace(b'warp=on', b'warp=off')
                doc = status(system, True)
                expected = json.loads((Path(__file__).parent / 'fixtures' / (name + '.json')).read_text())
                self.assertEqual(doc, expected)
                assert_contract(self, doc)
