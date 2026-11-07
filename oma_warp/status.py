"""Pure schema-1 status assembly; no I/O."""


def assemble_status(client, probe, update, job, now):
    return {
        'schema': 1, 'observed_at': now.isoformat().replace('+00:00', 'Z'),
        'client': client, 'probe': probe,
        'update': update if update is not None else {
            'latest': None, 'verified_at': None, 'available': None,
            'last_error': None, 'due': True,
        },
        'job': job, 'problems': [],
    }
