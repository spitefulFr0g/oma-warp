"""Pure schema-1 status assembly; no I/O."""

# Raised Problems, in precedence order: (code, fix, blocking, raised when).
# A blocking Problem nulls the facts below it, so it is always alone.
PROBLEMS = (
    ('service_stopped', 'start', True, lambda client, probe: client['service'] == 'stopped'),
    ('daemon_unresponsive', 'restart', True, lambda client, probe: client['daemon'] == 'unresponsive'),
    ('not_registered', 'register', True, lambda client, probe: client['registered'] is False),
)


def problems(client, probe, installed=None, operation_mode=None):
    if installed is False:
        return [{'code': 'not_installed', 'fix': 'install', 'blocking': True}]
    raised = [{'code': code, 'fix': fix, 'blocking': blocking}
              for code, fix, blocking, holds in PROBLEMS if holds(client, probe)]
    blocking = [problem for problem in raised if problem['blocking']]
    if blocking:
        return blocking[:1]
    if (operation_mode == 'warp' and client['connection'] == 'connected'
            and probe is not None and probe['trace'] == 'outside'):
        raised.append({'code': 'not_through_cloudflare', 'fix': 'reconnect', 'blocking': False})
    if (operation_mode == 'warp' and client['connection'] == 'connected'
            and probe is not None and probe.get('dns') in ('broken', 'bypassed', 'shared')):
        verdict = probe['dns']
        raised.append({'code': 'dns_' + verdict,
                       'fix': 'reconnect' if verdict == 'bypassed' else None, 'blocking': False})
    return raised


def assemble_status(client, probe, update, job, now, *, installed=None, operation_mode=None):
    return {
        'schema': 1, 'observed_at': now.isoformat().replace('+00:00', 'Z'),
        'client': client, 'probe': probe,
        'update': update if update is not None else {
            'latest': None, 'verified_at': None, 'available': None,
            'last_error': None, 'due': True,
        },
        'job': job, 'problems': problems(client, probe, installed, operation_mode),
    }
