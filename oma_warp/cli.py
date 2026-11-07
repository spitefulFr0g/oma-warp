"""Public backend entry point."""
import argparse
import json
from .client import gather
from .status import assemble_status
from .system import System


def main(argv=None, *, system=None):
    parser = argparse.ArgumentParser(prog='oma-warp')
    sub = parser.add_subparsers(dest='command', required=True)
    status = sub.add_parser('status')
    status.add_argument('--json', action='store_true')
    parser.parse_args(argv)
    system = system if system is not None else System()
    print(json.dumps(assemble_status(gather(system).client, None, None, None, system.now())))
    return 0
