"""Verified, disposable package builds and the Install terminal Job."""
from pathlib import Path
import subprocess

from .client import gather
from .jobs import run_job
from .packaging import PackagingError, prepare_build, build_package
from .repository import Repository, RepositoryError
from .update import timestamp


def build_and_install(system, release, deb, scratch):
    """Build a verified release and install it; caller owns the scratch lifetime.

    Shared with Update. Nothing is placed in the persistent cache except metadata.
    Pacman inherits terminal I/O and keeps its own confirmation prompt.
    """
    build = prepare_build(release, deb, scratch, system=system)
    package = build_package(build, system=system)
    result = system.run_terminal(['sudo', 'pacman', '-U', str(package)])
    return result.returncode if result.returncode > 0 else int(result.returncode < 0)


def install(system, job_id):
    def operation():
        facts = gather(system)
        if facts.installed is None:
            system.write('Cannot determine whether WARP is installed; refusing Install.')
            return 1
        if not facts.installed:
            try:
                repository = Repository(system=system)
                release = repository.latest()
                with system.temporary_directory(prefix='oma-warp-install-') as directory:
                    scratch = Path(directory)
                    deb = repository.download(release, scratch)
                    now = timestamp(system.now())
                    system.write_json(system.cache_dir / 'update.json', {
                        'latest': release.version, 'verified_at': now,
                        'attempted_at': now, 'last_error': None})
                    code = build_and_install(system, release, deb, scratch)
                    if code:
                        system.write('Could not install the WARP package.')
                        return code
            except (RepositoryError, PackagingError) as error:
                system.write(f'Install failed: {error}')
                return 1
            facts = gather(system)
        if facts.installed is not True:
            system.write('Cannot confirm the WARP package is installed.')
            return 1
        if facts.client['service'] is None:
            system.write('Cannot determine WARP service state.')
            return 1
        try:
            enabled = system.run(['systemctl', 'is-enabled', 'warp-svc'], timeout=1.5)
        except (OSError, subprocess.TimeoutExpired):
            system.write('Cannot determine whether the WARP service is enabled.')
            return 1
        state = enabled.stdout.strip()
        if not ((enabled.returncode == 0 and state == 'enabled') or
                (enabled.returncode == 1 and state == 'disabled')):
            system.write('Cannot confirm the WARP service can be enabled.')
            return 1
        if facts.client['service'] != 'running' or state != 'enabled':
            result = system.run_terminal(['sudo', 'systemctl', 'enable', '--now', 'warp-svc'])
            if result.returncode:
                return result.returncode if result.returncode > 0 else 1
            facts = gather(system)
        if facts.client['registered'] is None:
            system.write('Cannot determine WARP registration state; try Install again when the service responds.')
            return 1
        if facts.client['registered'] is False:
            result = system.run_terminal(['warp-cli', 'registration', 'new'])
            if result.returncode:
                return result.returncode if result.returncode > 0 else 1
        system.write('WARP is installed, running and registered.')
        return 0
    return run_job(system, 'install', job_id, operation)
