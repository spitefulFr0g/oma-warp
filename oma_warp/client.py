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
    installed: bool | None = None
    service_started: str | None = None


def gather(system):
    missing_package = object()

    def read(argv):
        try:
            result = system.run(argv, timeout=1.5)
            if result.returncode == 0:
                return result.stdout
            if argv == COMMANDS['package'] and result.returncode == 1 and result.stderr.strip() == "error: package 'cloudflare-warp-bin' was not found":
                return missing_package
            if argv[0] == 'warp-cli' and result.returncode == 1 and document(result.stdout).get('error') == 'MissingRegistration':
                return result.stdout
            return None
        except (OSError, subprocess.TimeoutExpired):
            return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        pending = {key: pool.submit(read, argv) for key, argv in COMMANDS.items()}
        raw = {key: future.result() for key, future in pending.items()}
    package_text = raw['package'] if isinstance(raw['package'], str) else ''
    package = dict(re.findall(r'^([^:\n]+?)\s*:\s*(.*)$', package_text, re.M))
    version = package.get('Version')
    if version is not None and not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+(?:-[0-9]+)?', version):
        version = None
    client = {'version': version.rsplit('-', 1)[0] if version else None,
              'service': None, 'restart_needed': None, 'daemon': None,
              'registered': None, 'connection': None}
    mode = document(raw['settings']).get('settings', {})
    mode = mode.get('operation_mode') if isinstance(mode, dict) else None
    service = dict(line.split('=', 1) for line in (raw['service'] or '').splitlines() if '=' in line)
    facts = ClientFacts(client, mode if isinstance(mode, str) else None,
                        installed=False if raw['package'] is missing_package else True if version else None,
                        service_started=service.get('ActiveEnterTimestamp'))
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
    missing = document(raw['status']).get('error') == 'MissingRegistration'
    if connection in ('Connected', 'Connecting', 'Disconnected') or missing:
        client['daemon'] = 'ok'
    elif raw['status'] is None:
        client['daemon'] = 'unresponsive'
    if client['daemon'] != 'ok':
        return facts
    client['connection'] = connection.lower() if isinstance(connection, str) else None
    registration = document(raw['registration'])
    if isinstance(registration.get('id'), str) and registration['id']:
        client['registered'] = True
    elif registration.get('error') == 'MissingRegistration' or missing:
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
    # System.run fixes LC_ALL=C and TZ=UTC for these local sources.
    # strptime's %Z also accepts the parent process's local timezone names;
    # never relabel such an ambiguous/non-UTC timestamp as UTC.
    for pattern in ('%a %b %d %H:%M:%S %Y', '%a %Y-%m-%d %H:%M:%S %Z',
                    '%a %d %b %Y %H:%M:%S %Z'):
        if '%Z' in pattern and value.rsplit(' ', 1)[-1] not in ('UTC', 'GMT'):
            continue
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None
