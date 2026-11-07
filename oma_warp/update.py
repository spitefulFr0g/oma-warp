"""Verified checks, disposable Update Jobs and the persistent update cache."""
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

from .repository import Repository, RepositoryError, NetworkError, VERSION_RE


def timestamp(now):
    return now.isoformat().replace('+00:00', 'Z')


def successful_cache(release, verified_at):
    """The verified result shared by Check, Install and Update."""
    return {'latest': release.version, 'verified_at': verified_at,
            'attempted_at': verified_at, 'last_error': None}


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
        document = successful_cache(release, timestamp(system.now()))
    except (RepositoryError, KeyboardInterrupt) as exc:
        # The Panel's watchdog sends SIGINT before resorting to a hard kill.
        # Persist a catchable timeout as a failed attempt for the next process.
        document = {'latest': document.get('latest'),
                    'verified_at': document.get('verified_at'),
                    'last_error': 'network' if isinstance(exc, (NetworkError, KeyboardInterrupt)) else 'verification'}
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


def update(system, job_id):
    """Verify afresh under one Job; only a proven newer release may install."""
    from .client import gather
    from .jobs import run_job
    from .install import build_and_install
    from .packaging import PackagingError
    from .restart import connection_state, restart_and_restore

    def operation():
        try:
            repository = Repository(system=system)
            release = repository.latest()
            with system.temporary_directory(prefix='oma-warp-update-') as directory:
                deb = repository.download(release, Path(directory))
                now = timestamp(system.now())
                system.write_json(system.cache_dir / 'update.json', successful_cache(release, now))
                facts = gather(system)
                installed = facts.client['version']
                if installed is None:
                    system.write('Cannot determine installed WARP version; refusing Update.')
                    return 1
                result = system.run(['vercmp', release.version, installed], timeout=1.5)
                if result.returncode:
                    system.write('Cannot compare WARP versions; refusing Update.')
                    return 1
                if int(result.stdout.strip()) <= 0:
                    system.write('Already current')
                    return 0
                if facts.client['service'] is None:
                    system.write('Cannot determine WARP service state; refusing Update.')
                    return 1
                prior = connection_state(system)
                stop_code = 0
                try:
                    code = build_and_install(system, release, deb, Path(directory))
                finally:
                    # Package hooks may start a previously stopped service even
                    # when pacman fails or is interrupted. Preserve user intent.
                    if facts.client['service'] == 'stopped' and gather(system).client['service'] != 'stopped':
                        result = system.run_terminal(['sudo', 'systemctl', 'stop', 'warp-svc'])
                        stop_code = result.returncode if result.returncode > 0 else int(result.returncode < 0)
                if code:
                    system.write('Could not install the WARP package.')
                    return code
                if facts.client['service'] == 'running':
                    return restart_and_restore(system, prior=prior)
                system.write('WARP did not reconnect')
                return stop_code
        except (RepositoryError, PackagingError, ValueError) as error:
            system.write(f'Update failed: {error}')
            return 1
    return run_job(system, 'update', job_id, operation)
