"""Pure schema-1 status assembly; no I/O."""

# Raised Problems, in precedence order: (code, fix, blocking, raised when).
# A blocking Problem nulls the facts below it, so it is always alone.
PROBLEMS = (
    ('service_stopped', 'start', True, lambda client, probe: client['service'] == 'stopped'),
)


def problems(client, probe, operation_mode=None):
    raised = [{'code': code, 'fix': fix, 'blocking': blocking}
              for code, fix, blocking, holds in PROBLEMS if holds(client, probe)]
    blocking = [problem for problem in raised if problem['blocking']]
    if blocking:
        return blocking[:1]
    if (operation_mode == 'warp' and client['connection'] == 'connected'
            and probe is not None and probe['trace'] == 'outside'):
        raised.append({'code': 'not_through_cloudflare', 'fix': 'reconnect', 'blocking': False})
    return raised


def assemble_status(client, probe, update, job, now, operation_mode=None):
    return {
        'schema': 1, 'observed_at': now.isoformat().replace('+00:00', 'Z'),
        'client': client, 'probe': probe,
        'update': update if update is not None else {
            'latest': None, 'verified_at': None, 'available': None,
            'last_error': None, 'due': True,
        },
        'job': job, 'problems': problems(client, probe, operation_mode),
    }
