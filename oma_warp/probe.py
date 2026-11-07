"""Bounded trace acquisition and connection-scoped runtime cache."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import http.client
import subprocess
import json
from queue import Empty, Queue
from threading import Thread

from .client import COMMANDS, document, gather

TRACE_URL = 'https://www.cloudflare.com/cdn-cgi/trace'


def tag(facts):
    return {'connection': facts.client['connection'], 'service_started': facts.service_started}


def invalidate(system):
    if system.runtime_dir is not None:
        try:
            system.remove_file(system.runtime_dir / 'probe.json')
        except OSError:
            pass


def cached_probe(system, facts):
    if system.runtime_dir is None:
        return None
    try:
        record = json.loads(system.read_text(system.runtime_dir / 'probe.json'))
    except (OSError, ValueError, TypeError):
        return None
    if (isinstance(record, dict) and record.get('tag') == tag(facts)
            and facts.service_started and facts.client['service'] == 'running'
            and facts.client['connection'] is not None):
        probe = record.get('probe')
        if (isinstance(probe, dict) and set(probe) == {'checked_at', 'trace', 'ip', 'colo', 'country', 'dns'}
                and probe['trace'] in ('through', 'outside', 'failed')):
            return probe
    invalidate(system)
    return None


def identity(system):
    """Short pre/post snapshots leave room for the four-second trace budget."""
    def read(key):
        try:
            result = system.run(COMMANDS[key], timeout=0.2)
            return result.stdout if result.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired):
            return ''
    with ThreadPoolExecutor(max_workers=2) as pool:
        service_future = pool.submit(read, 'service')
        connection_future = pool.submit(read, 'status')
        service = dict(line.split('=', 1) for line in service_future.result().splitlines() if '=' in line)
        connection = document(connection_future.result()).get('status')
    if (service.get('ActiveState') not in ('active', 'reloading')
            or not service.get('ActiveEnterTimestamp')
            or connection not in ('Connected', 'Connecting', 'Disconnected')):
        return None
    return {'connection': connection.lower(), 'service_started': service['ActiveEnterTimestamp']}


def failed(system):
    return {'checked_at': system.now().isoformat().replace('+00:00', 'Z'),
            'trace': 'failed', 'ip': None, 'colo': None, 'country': None, 'dns': None}


def trace(system):
    result = failed(system)
    try:
        body = system.fetch(TRACE_URL, timeout=4, limit=16384).decode('utf-8')
        fields = {}
        for line in body.splitlines():
            key, separator, value = line.partition('=')
            if separator:
                if key in fields:
                    raise ValueError('duplicate trace field')
                fields[key] = value
        ipaddress.ip_address(fields['ip'])
        verdict = {'on': 'through', 'plus': 'through', 'off': 'outside'}[fields['warp']]
        if not fields['colo'].isascii() or not fields['colo'].isalpha() or len(fields['colo']) != 3:
            raise ValueError('invalid colo')
        if not fields['loc'].isascii() or not fields['loc'].isalpha() or len(fields['loc']) != 2:
            raise ValueError('invalid country')
        result.update({'trace': verdict, 'ip': fields['ip'],
                       'colo': fields['colo'], 'country': fields['loc']})
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        pass
    return result


def probe_status(system):
    before = identity(system)
    started = system.monotonic()
    pending = Queue(maxsize=1)
    # urllib's socket timeout is not a total deadline (a server can trickle
    # bytes). A daemon worker cannot hold the command open after the budget.
    # The worker only returns data; it can never publish a late cache entry.
    Thread(target=lambda: pending.put(trace(system)), daemon=True).start()
    facts = gather(system)
    try:
        result = pending.get(timeout=max(0, 4 - (system.monotonic() - started)))
    except Empty:
        result = failed(system)
    after = identity(system)
    if before is None or before != tag(facts) or before != after:
        invalidate(system)
        return facts, None
    if system.runtime_dir is not None:
        try:
            system.atomic_write(system.runtime_dir / 'probe.json', json.dumps({'tag': before, 'probe': result}))
        except OSError:
            pass
    return facts, result
