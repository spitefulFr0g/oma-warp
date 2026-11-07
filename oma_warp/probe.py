"""Bounded concurrent trace/DNS acquisition and connection-scoped cache."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import http.client
import subprocess
import json
import re
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
            return probe | {'dns': probe['dns'] if facts.operation_mode == 'warp'
                            and facts.client['connection'] == 'connected' else None}
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


def warp_mode(system):
    try:
        result = system.run(COMMANDS['settings'], timeout=0.2)
        settings = document(result.stdout).get('settings') if result.returncode == 0 else None
        return isinstance(settings, dict) and settings.get('operation_mode') == 'warp'
    except (OSError, subprocess.TimeoutExpired):
        return False


def dns_read(system, argv):
    try:
        return system.run(argv, timeout=4)
    except subprocess.TimeoutExpired:
        return 'timeout'
    except OSError:
        return None


def dns(answers, domains):
    if answers == 'timeout' or (answers is not None and answers.returncode == 124):
        return 'broken'
    if answers is not None and answers.returncode == 2:
        return 'bypassed'
    if (answers is None or answers.returncode != 0 or domains is None
            or domains == 'timeout' or domains.returncode != 0):
        return None
    rows = [line.split() for line in answers.stdout.splitlines() if line.strip()]
    if not rows or any(len(row) not in (2, 3) or row[0] not in ('127.0.2.2', '127.0.2.3')
                       or row[1] not in ('STREAM', 'DGRAM', 'RAW')
                       or (len(row) == 3 and row[2] != 'connectivity-check.warp-svc') for row in rows):
        return None
    claims = []
    seen = set()
    for line in domains.stdout.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'(Global|Link [0-9]+ \([^()]+\)):\s*(.*)', line)
        if match is None or match[1] in seen:
            return None
        seen.add(match[1])
        if '~.' in match[2].split():
            claims.append(match[1])
    if not seen:
        return None
    if any(claim != 'Global' and claim.endswith(' (CloudflareWARP)') for claim in claims):
        return 'ok' if len(claims) == 1 else 'shared'
    return 'shared' if claims else None


def probe_status(system):
    before = identity(system)
    # A short mode read keeps the four-second checks concurrent with gather.
    # Together with the two identity snapshots, it reserves 0.4 s for status
    # assembly (including the bounded version comparison) under the 5 s limit.
    check_dns = before is not None and before['connection'] == 'connected' and warp_mode(system)
    started = system.monotonic()
    pending = Queue(maxsize=3)
    # urllib's socket timeout is not a total deadline (a server can trickle
    # bytes). A daemon worker cannot hold the command open after the budget.
    # The worker only returns data; it can never publish a late cache entry.
    Thread(target=lambda: pending.put(('trace', trace(system))), daemon=True).start()
    if check_dns:
        Thread(target=lambda: pending.put(('answers', dns_read(system,
            ['timeout', '4', 'getent', 'ahostsv4', 'connectivity-check.warp-svc']))), daemon=True).start()
        Thread(target=lambda: pending.put(('domains', dns_read(system,
            ['resolvectl', 'domain']))), daemon=True).start()
    facts = gather(system)
    results = {}
    for _ in range(3 if check_dns else 1):
        try:
            key, value = pending.get(timeout=max(0, 4 - (system.monotonic() - started)))
            results[key] = value
        except Empty:
            break
    result = results.get('trace', failed(system))
    if check_dns and facts.operation_mode == 'warp' and facts.client['connection'] == 'connected':
        result['dns'] = dns(results.get('answers', 'timeout'), results.get('domains'))
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
