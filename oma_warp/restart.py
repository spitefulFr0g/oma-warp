"""Restart and restore, shared by terminal Restart and Update Jobs."""
import subprocess

from .client import document
from .jobs import run_job
from .probe import invalidate


def connection_state(system, *, timeout=1.5):
    """Read only a definite connected/disconnected state; all else is unknown."""
    try:
        result = system.run(['warp-cli', '-j', 'status'], timeout=timeout)
        state = document(result.stdout).get('status') if result.returncode == 0 else None
        return state if state in ('Connected', 'Disconnected') else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def restart_and_restore(system):
    """Run inside the caller's Job; never acquire nested Job ownership.

    Update calls this only when the service was running before installation.
    Polling observes automatic restoration; it never retries a mutation.
    """
    prior = connection_state(system)
    invalidate(system)
    result = system.run_terminal(['sudo', 'systemctl', 'restart', 'warp-svc'])
    if result.returncode != 0:
        system.write('WARP did not reconnect')
        return result.returncode if result.returncode > 0 else 1
    deadline = system.monotonic() + 15
    current = None
    while (remaining := deadline - system.monotonic()) > 0:
        current = connection_state(system, timeout=min(1.5, remaining))
        if current is not None and (prior is None or current == prior):
            break
        remaining = deadline - system.monotonic()
        if remaining > 0:
            system.wait(min(0.5, remaining))
    else:
        # Observe once at the deadline before deciding a fallback is needed.
        current = connection_state(system)
    if prior is not None and current != prior:
        try:
            system.run(['warp-cli', 'connect' if prior == 'Connected' else 'disconnect'], timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        # A toggle acknowledges a request before the state necessarily changes.
        # Observe it briefly, without issuing another toggle or restart.
        fallback_deadline = system.monotonic() + 5
        current = connection_state(system)
        while current != prior and (remaining := fallback_deadline - system.monotonic()) > 0:
            system.wait(min(0.5, remaining))
            remaining = fallback_deadline - system.monotonic()
            current = connection_state(system, timeout=min(1.5, remaining) if remaining > 0 else 1.5)
    system.write('Connected again' if current == 'Connected' else 'WARP did not reconnect')
    return int(prior is not None and current != prior)


def restart(system, job_id):
    return run_job(system, 'restart', job_id, lambda: restart_and_restore(system))
