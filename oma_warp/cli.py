"""Public backend entry point."""
import argparse
import json
from .client import gather
from .connection import switch
from .status import assemble_status
from .system import System
from .uninstall import uninstall


def main(argv=None, *, system=None):
    parser = argparse.ArgumentParser(prog='oma-warp')
    sub = parser.add_subparsers(dest='command', required=True)
    status = sub.add_parser('status')
    status.add_argument('--json', action='store_true')
    sub.add_parser('connect')
    sub.add_parser('disconnect')
    sub.add_parser('uninstall')
    args = parser.parse_args(argv)
    system = system if system is not None else System()
    if args.command in ('connect', 'disconnect'):
        return switch(system, args.command)
    if args.command == 'uninstall':
        return uninstall(system)
    print(json.dumps(assemble_status(gather(system).client, None, None, None, system.now())))
    return 0
