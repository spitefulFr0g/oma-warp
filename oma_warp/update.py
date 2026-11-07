"""Verified update checks and the persistent update cache."""
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

from .repository import Repository, RepositoryError, NetworkError, VERSION_RE


def timestamp(now):
    return now.isoformat().replace('+00:00', 'Z')


def read_cache(system):
    value = system.read_json(system.cache_dir / 'update.json')
    if not isinstance(value, dict):
        return {}
    latest, verified = value.get('latest'), value.get('verified_at')
    if latest is not None and (not isinstance(latest, str) or not VERSION_RE.fullmatch(latest)):
        return {}
    if (latest is None) != (verified is None):
        return {}
    if value.get('last_error') not in (None, 'network', 'verification'):
        return {}
    for date in (verified, value.get('attempted_at')):
        if date is None:
            continue
        try:
            if datetime.fromisoformat(date).utcoffset() is None:
                return {}
        except (ValueError, TypeError):
            return {}
    return value


def check(system):
    document = read_cache(system)
    try:
        repository = Repository(system=system)
        release = repository.latest()
        with system.temporary_directory(prefix='oma-warp-check-') as scratch:
            repository.download(release, Path(scratch))
        document = {'latest': release.version, 'verified_at': timestamp(system.now()),
                    'last_error': None}
    except RepositoryError as exc:
        document = {'latest': document.get('latest'),
                    'verified_at': document.get('verified_at'),
                    'last_error': 'network' if isinstance(exc, NetworkError) else 'verification'}
    document['attempted_at'] = timestamp(system.now())
    system.write_json(system.cache_dir / 'update.json', document)
    return document


def status_update(system, installed):
    cache = read_cache(system)
    latest = cache.get('latest')
    available = None
    if latest is not None and installed is not None:
        try:
            result = system.run(['vercmp', latest, installed], timeout=0.25)
            if result.returncode == 0:
                available = int(result.stdout.strip()) > 0
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    due = True
    try:
        attempted = datetime.fromisoformat(cache['attempted_at'])
        due = system.now() - attempted > timedelta(hours=12)
    except (KeyError, ValueError, TypeError):
        pass
    return {'latest': latest, 'verified_at': cache.get('verified_at'),
            'available': available, 'last_error': cache.get('last_error'), 'due': due}
