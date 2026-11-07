"""Resumable terminal cleanup, separate from Panel Jobs."""
import subprocess
from pathlib import Path

from .client import document

PACKAGE = 'cloudflare-warp-bin'
STATE_DIR = Path('/var/lib/cloudflare-warp')
SERVICE_QUERY = ['systemctl', 'show', 'warp-svc',
                 '--property=LoadState,ActiveState,UnitFileState']


class UninstallError(Exception):
    pass


def uninstall(system):
    try:
        if not system.confirm('Uninstall WARP, its registration and state, and the oma-warp plugin?'):
            system.write('Uninstall cancelled.')
            return 0
        cleanup(system)
        system.write('Uninstall complete.')
        return 0
    except (UninstallError, OSError, subprocess.SubprocessError, EOFError) as error:
        system.write(f'Uninstall stopped: {error}. Run oma-warp uninstall again to resume.')
        return 1
    except KeyboardInterrupt:
        system.write('Uninstall interrupted. Run oma-warp uninstall again to resume.')
        return 130


def cleanup(system):
    def query(argv):
        return system.run(argv, timeout=1.5)

    def remove(argv):
        if system.run_terminal(argv).returncode != 0:
            raise UninstallError('command failed: ' + ' '.join(argv))

    package = query(['pacman', '-Qq', PACKAGE])
    installed = package.returncode == 0 and package.stdout.strip() == PACKAGE
    if not installed and not (package.returncode == 1 and
                              package.stderr.strip() == f"error: package '{PACKAGE}' was not found"):
        raise UninstallError('could not determine whether the WARP package is installed')

    result = query(SERVICE_QUERY)
    if result.returncode != 0:
        raise UninstallError('could not read the WARP service')
    service = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    active = service.get('ActiveState')
    if service.get('LoadState') not in ('loaded', 'not-found', 'masked') or active not in (
            'active', 'reloading', 'inactive', 'failed', 'activating', 'deactivating'):
        raise UninstallError('could not determine the WARP service state')
    running = active not in ('inactive', 'failed')
    if running:
        result = query(['warp-cli', '-j', 'status'])
        status = document(result.stdout)
        connection = status.get('status')
        missing_registration = result.returncode in (0, 1) and status.get('error') == 'MissingRegistration'
        if not missing_registration and (result.returncode != 0 or connection not in ('Connected', 'Connecting', 'Disconnected')):
            raise UninstallError('could not determine the WARP connection state')
        if not missing_registration and connection != 'Disconnected':
            remove(['warp-cli', 'disconnect'])
        result = query(['warp-cli', '-j', 'registration', 'show'])
        registration = document(result.stdout)
        if result.returncode == 0 and isinstance(registration.get('id'), str) and registration['id']:
            remove(['warp-cli', 'registration', 'delete'])
        elif not (result.returncode in (0, 1) and registration.get('error') == 'MissingRegistration'):
            raise UninstallError('could not determine the WARP registration state')
        remove(['sudo', 'systemctl', 'stop', 'warp-svc'])
    else:
        # An inactive service cannot carry traffic. Its daemon facts are unavailable;
        # residual local registration is removed with STATE_DIR below.
        system.write('WARP service is stopped; remaining local registration will be removed with its state.')
    enabled = service.get('UnitFileState')
    if enabled in ('enabled', 'enabled-runtime', 'linked', 'linked-runtime'):
        remove(['sudo', 'systemctl', 'disable', 'warp-svc'])
    elif enabled not in ('disabled', 'static', 'indirect', 'masked', 'masked-runtime', '') or (
            enabled == '' and service.get('LoadState') != 'not-found'):
        raise UninstallError('could not determine whether the WARP service is enabled')
    if installed:
        remove(['sudo', 'pacman', '-Rns', '--noconfirm', PACKAGE])
    if system.path_exists(STATE_DIR):
        remove(['sudo', 'rm', '-rf', '--', str(STATE_DIR)])
    for path in (system.cache_dir, system.runtime_dir):
        if path is not None and system.path_exists(path):
            system.remove_tree(path)
    if system.path_exists(system.plugin_dir):
        remove(['omarchy', 'plugin', 'remove', 'spitefulfr0g.oma-warp', '--yes'])
