"""Concurrent, bounded, read-only client facts."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import subprocess

COMMANDS = {
    'package': ['pacman', '-Qi', 'cloudflare-warp-bin'],
    'service': ['systemctl', 'show', 'warp-svc', '--property=ActiveState,ActiveEnterTimestamp'],
    'status': ['warp-cli', '-j', 'status'],
    'registration': ['warp-cli', '-j', 'registration', 'show'],
    'settings': ['warp-cli', '-j', 'settings'],
}


@dataclass(frozen=True)
class ClientFacts:
    client: dict
    operation_mode: str | None
    service_started: str | None = None


def gather(system):
    def read(argv):
        try:
            result = system.run(argv, timeout=1.5)
            if result.returncode == 0:
                return result.stdout
            if argv[-2:] == ['registration', 'show'] and document(result.stdout).get('error') == 'MissingRegistration':
                return result.stdout
            return None
        except (OSError, subprocess.TimeoutExpired):
            return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        pending = {key: pool.submit(read, argv) for key, argv in COMMANDS.items()}
        raw = {key: future.result() for key, future in pending.items()}
    package = dict(re.findall(r'^([^:\n]+?)\s*:\s*(.*)$', raw['package'] or '', re.M))
    version = package.get('Version')
    client = {'version': version.rsplit('-', 1)[0] if version else None,
              'service': None, 'restart_needed': None, 'daemon': None,
              'registered': None, 'connection': None}
    mode = document(raw['settings']).get('settings', {})
    mode = mode.get('operation_mode') if isinstance(mode, dict) else None
    service = dict(line.split('=', 1) for line in (raw['service'] or '').splitlines() if '=' in line)
    facts = ClientFacts(client, mode if isinstance(mode, str) else None,
                        service.get('ActiveEnterTimestamp'))
    if not version:
        return facts
    active = service.get('ActiveState')
    if active in ('active', 'reloading'):
        client['service'] = 'running'
    elif active in ('inactive', 'failed', 'activating', 'deactivating', 'maintenance'):
        client['service'] = 'stopped'
    if client['service'] is None:
        return facts
    installed = parse_time(package.get('Install Date'))
    started = parse_time(service.get('ActiveEnterTimestamp'))
    if installed is not None and started is not None:
        client['restart_needed'] = started < installed
    if client['service'] != 'running':
        return facts
    connection = document(raw['status']).get('status')
    client['daemon'] = 'ok' if connection in ('Connected', 'Connecting', 'Disconnected') else 'unresponsive'
    if client['daemon'] != 'ok':
        return facts
    client['connection'] = connection.lower()
    registration = document(raw['registration'])
    if isinstance(registration.get('id'), str) and registration['id']:
        client['registered'] = True
    elif registration.get('error') == 'MissingRegistration':
        client['registered'] = False
        client['connection'] = None
    return facts


def document(text):
    try:
        value = json.loads(text or '')
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def parse_time(value):
    if not value:
        return None
    # System.run fixes both LC_ALL=C and TZ=UTC for these local sources.
    for pattern in ('%a %b %d %H:%M:%S %Y', '%a %Y-%m-%d %H:%M:%S %Z',
                    '%a %d %b %Y %H:%M:%S %Z'):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None
