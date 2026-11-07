"""Terminal Jobs and their short-lived, process-identity checked status."""
from datetime import datetime
import json
import subprocess

ACTIONS = ('install', 'update', 'restart', 'start', 'register')


def live_job(system):
    """Return only the public Job fields; treat untrusted/dead records as absent."""
    if system.runtime_dir is None:
        return None
    try:
        record = json.loads(system.read_text(system.runtime_dir / 'job.json'))
        if not isinstance(record, dict):
            return None
        pid = record.get('pid')
        started = record.get('started_at')
        identity = record.get('process_start_time')
        if (type(pid) is not int or pid <= 0 or record.get('action') not in ACTIONS
                or not isinstance(record.get('job_id'), str) or not record['job_id']
                or not isinstance(started, str)
                or datetime.fromisoformat(started).utcoffset() is None
                or not isinstance(identity, str) or not identity.isdecimal()):
            return None
        if system.process_start_time(pid) != identity:
            return None
        return {'action': record['action'], 'started_at': started}
    except (OSError, ValueError, TypeError):
        return None


def run_job(system, action, job_id, operation):
    """Run operation() under exclusive ownership, publishing status for its lifetime.

    Future Jobs supply their terminal operation here. The lock file is persistent:
    unlinking it would let contenders lock different inodes. Kernel locks are
    released on process death, so a later Job can replace an abandoned record.
    """
    if action not in ACTIONS or not isinstance(job_id, str) or not job_id.strip():
        system.write('Job refused: invalid action or job id.')
        return 1
    if system.runtime_dir is None:
        system.write('Job refused: XDG_RUNTIME_DIR is unavailable.')
        return 1
    try:
        with system.exclusive_lock(system.runtime_dir / 'job.lock') as acquired:
            if not acquired or live_job(system) is not None:
                system.write('Job refused: another Job is running.')
                return 1
            pid = system.current_pid
            identity = system.process_start_time(pid)
            if identity is None:
                system.write('Job refused: cannot determine process identity.')
                return 1
            record = {'job_id': job_id, 'action': action,
                      'started_at': system.now().isoformat().replace('+00:00', 'Z'),
                      'pid': pid, 'process_start_time': identity}
            try:
                system.atomic_write(system.runtime_dir / 'job.json', json.dumps(record))
                return operation()
            finally:
                system.remove_file(system.runtime_dir / 'job.json')
    except KeyboardInterrupt:
        system.write('Job interrupted.')
        return 130
    except (OSError, subprocess.SubprocessError) as error:
        system.write(f'Job failed: {error}')
        return 1


def start(system, job_id):
    def operation():
        result = system.run_terminal(['sudo', 'systemctl', 'enable', '--now', 'warp-svc'])
        if result.returncode != 0:
            system.write('Could not start the WARP service.')
            return result.returncode if result.returncode > 0 else 1
        system.write('WARP service started.')
        return 0
    return run_job(system, 'start', job_id, operation)
