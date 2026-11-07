"""Pure schema-1 status assembly; no I/O."""

# Raised Problems, in precedence order: (code, fix, blocking, raised when).
# A blocking Problem nulls the facts below it, so it is always alone.
PROBLEMS = (
    ('service_stopped', 'start', True, lambda client, probe: client['service'] == 'stopped'),
    ('daemon_unresponsive', 'restart', True, lambda client, probe: client['daemon'] == 'unresponsive'),
    ('not_registered', 'register', True, lambda client, probe: client['registered'] is False),
)


def problems(client, probe, installed=None):
    if installed is False:
        return [{'code': 'not_installed', 'fix': 'install', 'blocking': True}]
    raised = [{'code': code, 'fix': fix, 'blocking': blocking}
              for code, fix, blocking, holds in PROBLEMS if holds(client, probe)]
    blocking = [problem for problem in raised if problem['blocking']]
    return blocking[:1] or raised


def assemble_status(client, probe, update, job, now, *, installed=None):
    return {
        'schema': 1, 'observed_at': now.isoformat().replace('+00:00', 'Z'),
        'client': client, 'probe': probe,
        'update': update if update is not None else {
            'latest': None, 'verified_at': None, 'available': None,
            'last_error': None, 'due': True,
        },
        'job': job, 'problems': problems(client, probe, installed),
    }
