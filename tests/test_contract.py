"""Shared Fixture contract; also consumed by the later Panel tests."""
from datetime import datetime
import ipaddress
import json
from pathlib import Path
import unittest

# The contract's Problem table, in precedence order: code -> (fix, blocking).
PROBLEMS = {
    'not_installed': ('install', True),
    'service_stopped': ('start', True),
    'daemon_unresponsive': ('restart', True),
    'not_registered': ('register', True),
    'not_through_cloudflare': ('reconnect', False),
    'dns_broken': (None, False),
    'dns_bypassed': ('reconnect', False),
    'dns_shared': (None, False),
}


def assert_contract(test, doc):
    test.assertEqual(set(doc), {'schema', 'observed_at', 'client', 'probe', 'update', 'job', 'problems'})
    test.assertEqual(type(doc['schema']), int)
    test.assertEqual(doc['schema'], 1)
    def timestamp(value):
        test.assertIsInstance(value, str)
        test.assertIsNotNone(datetime.fromisoformat(value).utcoffset())
    def nullable(value, kind):
        test.assertTrue(value is None or type(value) is kind)
    timestamp(doc['observed_at'])
    client = doc['client']
    test.assertEqual(set(client), {'version', 'service', 'restart_needed', 'daemon', 'registered', 'connection'})
    nullable(client['version'], str)
    nullable(client['restart_needed'], bool)
    nullable(client['registered'], bool)
    test.assertIn(client['service'], (None, 'running', 'stopped'))
    test.assertIn(client['daemon'], (None, 'ok', 'unresponsive'))
    test.assertIn(client['connection'], (None, 'connected', 'connecting', 'disconnected'))
    if client['version'] is None:
        for key in ('service', 'restart_needed', 'daemon', 'registered', 'connection'):
            test.assertIsNone(client[key])
    if client['service'] != 'running':
        test.assertIsNone(client['daemon'])
    if client['daemon'] != 'ok':
        test.assertIsNone(client['registered'])
        test.assertIsNone(client['connection'])
    if client['registered'] is False:
        test.assertIsNone(client['connection'])
    probe = doc['probe']
    if probe is not None:
        test.assertEqual(set(probe), {'checked_at', 'trace', 'ip', 'colo', 'country', 'dns'})
        timestamp(probe['checked_at'])
        test.assertIn(probe['trace'], ('through', 'outside', 'failed'))
        test.assertIn(probe['dns'], (None, 'ok', 'bypassed', 'broken', 'shared'))
        for key in ('ip', 'colo', 'country'):
            nullable(probe[key], str)
            if probe['trace'] == 'failed':
                test.assertIsNone(probe[key])
        if probe['ip'] is not None:
            ipaddress.ip_address(probe['ip'])
        if client['connection'] != 'connected':
            test.assertIsNone(probe['dns'])
    update = doc['update']
    test.assertEqual(set(update), {'latest', 'verified_at', 'available', 'last_error', 'due'})
    nullable(update['latest'], str)
    nullable(update['available'], bool)
    test.assertIs(type(update['due']), bool)
    test.assertIn(update['last_error'], (None, 'network', 'verification'))
    if update['verified_at'] is not None:
        timestamp(update['verified_at'])
    if update['latest'] is None:
        test.assertIsNone(update['verified_at'])
    if update['latest'] is None or client['version'] is None:
        test.assertIsNone(update['available'])
    if doc['job'] is not None:
        test.assertEqual(set(doc['job']), {'action', 'started_at'})
        test.assertIn(doc['job']['action'], ('install', 'update', 'restart', 'start', 'register'))
        timestamp(doc['job']['started_at'])
    test.assertIsInstance(doc['problems'], list)
    for problem in doc['problems']:
        test.assertEqual(set(problem), {'code', 'fix', 'blocking'})
        test.assertIn(problem['code'], PROBLEMS)
        test.assertIn(problem['fix'], (None, 'install', 'start', 'restart', 'register', 'reconnect'))
        test.assertIs(type(problem['blocking']), bool)
        test.assertEqual((problem['fix'], problem['blocking']), PROBLEMS[problem['code']])
    codes = [problem['code'] for problem in doc['problems']]
    test.assertEqual(len(codes), len(set(codes)))
    test.assertEqual(codes, sorted(codes, key=list(PROBLEMS).index))
    if any(problem['blocking'] for problem in doc['problems']):
        test.assertEqual(len(codes), 1)
    dns_codes = [code for code in codes if code.startswith('dns_')]
    test.assertLessEqual(len(dns_codes), 1)
    expected_dns = ('dns_' + probe['dns'] if probe is not None
                    and probe['dns'] in ('broken', 'bypassed', 'shared') else None)
    test.assertEqual(dns_codes, [expected_dns] if expected_dns else [])
    if any(not problem['blocking'] for problem in doc['problems']):
        test.assertEqual(client['connection'], 'connected')
        test.assertIsNotNone(probe)
    test.assertEqual('service_stopped' in codes, client['service'] == 'stopped')
    test.assertEqual('daemon_unresponsive' in codes, client['daemon'] == 'unresponsive')
    test.assertEqual('not_registered' in codes, client['registered'] is False)
    if 'not_installed' in codes:
        test.assertIsNone(client['version'])
    if client['daemon'] == 'unresponsive':
        test.assertEqual(client['service'], 'running')


class ContractTests(unittest.TestCase):
    def test_every_shared_fixture_conforms(self):
        fixtures = list((Path(__file__).parent / 'fixtures').glob('*.json'))
        self.assertTrue(fixtures)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                assert_contract(self, json.loads(fixture.read_text()))

    def test_contract_rejects_missing_keys_wrong_types_and_invalid_dependencies(self):
        import copy
        original = json.loads((Path(__file__).parent / 'fixtures/off.json').read_text())
        for change in ('missing', 'enum', 'boolean', 'dependency', 'schema'):
            doc = copy.deepcopy(original)
            if change == 'missing': del doc['update']['due']
            if change == 'enum': doc['client']['connection'] = 'online'
            if change == 'boolean': doc['client']['registered'] = 1
            if change == 'dependency': doc['client']['service'] = 'stopped'
            if change == 'schema': doc['schema'] = True
            with self.subTest(change=change), self.assertRaises(AssertionError):
                assert_contract(self, doc)

    def test_contract_rejects_problem_lists_that_break_the_precedence_rules(self):
        import copy
        original = json.loads((Path(__file__).parent / 'fixtures/unconfirmed.json').read_text())
        original['probe'] = {'checked_at': '2026-10-02T00:00:00Z', 'trace': 'outside', 'ip': '203.0.113.7',
                             'colo': 'XXX', 'country': 'XX', 'dns': 'bypassed'}
        def problem(code):
            fix, blocking = PROBLEMS[code]
            return {'code': code, 'fix': fix, 'blocking': blocking}
        original['problems'] = [problem('not_through_cloudflare'), problem('dns_bypassed')]
        assert_contract(self, original)
        cases = {
            'out of order': [problem('dns_bypassed'), problem('not_through_cloudflare')],
            'two blocking': [problem('service_stopped'), problem('not_registered')],
            'blocking not alone': [problem('service_stopped'), problem('dns_bypassed')],
            'two dns codes': [problem('dns_broken'), problem('dns_bypassed')],
            'duplicate': [problem('dns_bypassed'), problem('dns_bypassed')],
            'wrong fix': [dict(problem('service_stopped'), fix='restart')],
            'fix for a fixless code': [dict(problem('dns_shared'), fix='reconnect')],
            'wrong blocking': [dict(problem('not_through_cloudflare'), blocking=True)],
        }
        for name, problems in cases.items():
            doc = copy.deepcopy(original)
            doc['problems'] = problems
            with self.subTest(case=name), self.assertRaises(AssertionError):
                assert_contract(self, doc)


def test_contract_requires_blocking_problem_to_match_its_fact():
    import copy
    test = unittest.TestCase()
    fixtures = Path(__file__).parent / 'fixtures'
    for name in ('daemon_unresponsive', 'not_registered'):
        doc = json.loads((fixtures / f'{name}.json').read_text())
        doc['problems'] = []
        with test.assertRaises(AssertionError):
            assert_contract(test, doc)
    original = json.loads((fixtures / 'off.json').read_text())
    for code in ('not_installed', 'daemon_unresponsive', 'not_registered'):
        doc = copy.deepcopy(original)
        fix, blocking = PROBLEMS[code]
        doc['problems'] = [dict(code=code, fix=fix, blocking=blocking)]
        with test.assertRaises(AssertionError):
            assert_contract(test, doc)


def test_contract_requires_dns_problem_to_match_probe_and_connected_client():
    import copy
    test = unittest.TestCase()
    original = json.loads((Path(__file__).parent / 'fixtures/dns_bypassed.json').read_text())
    for change in ('missing', 'wrong verdict', 'no probe', 'disconnected'):
        doc = copy.deepcopy(original)
        if change == 'missing': doc['problems'] = []
        if change == 'wrong verdict': doc['probe']['dns'] = 'broken'
        if change == 'no probe': doc['probe'] = None
        if change == 'disconnected':
            doc['client']['connection'] = 'disconnected'
            doc['probe']['dns'] = None
        with test.subTest(change=change), test.assertRaises(AssertionError):
            assert_contract(test, doc)
