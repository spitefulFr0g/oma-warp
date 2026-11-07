"""Switch WARP on and off for the Panel; no root, no prompts."""
import subprocess
import sys

TIMEOUT = 10


def switch(system, command):
    try:
        result = system.run(['warp-cli', command], timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return fail(command, f'warp-cli timed out after {TIMEOUT} s')
    except OSError as error:
        return fail(command, error.strerror or str(error))
    if result.returncode != 0:
        return fail(command, (result.stderr or result.stdout or '').strip() or f'warp-cli exited {result.returncode}')
    return 0


def fail(command, reason):
    print(f'oma-warp {command}: {reason}', file=sys.stderr)
    return 1
