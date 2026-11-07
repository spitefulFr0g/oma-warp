"""Public backend entry point."""
import argparse
import json
from .client import gather
from .connection import switch
from .jobs import live_job, register, start
from .status import assemble_status
from .system import System
from .uninstall import uninstall
from .update import check, status_update


def main(argv=None, *, system=None):
    parser = argparse.ArgumentParser(prog='oma-warp')
    sub = parser.add_subparsers(dest='command', required=True)
    status = sub.add_parser('status')
    status.add_argument('--json', action='store_true')
    check_parser = sub.add_parser('check')
    check_parser.add_argument('--json', action='store_true')
    sub.add_parser('connect')
    sub.add_parser('disconnect')
    sub.add_parser('uninstall')
    for action in ('start', 'register'):
        job = sub.add_parser(action)
        job.add_argument('--job-id', required=True)
    args = parser.parse_args(argv)
    system = system if system is not None else System()
    if args.command == 'check':
        document = check(system)
        print(json.dumps(document) if args.json else
              f"Latest verified release: {document['latest']}\nVerified at: {document['verified_at']}" +
              (f"\nCheck failed: {document['last_error']}" if document['last_error'] else ''))
        return int(document['last_error'] is not None)
    if args.command in ('connect', 'disconnect'):
        return switch(system, args.command)
    if args.command in ('start', 'register'):
        return (start if args.command == 'start' else register)(system, args.job_id)
    if args.command == 'uninstall':
        return uninstall(system)
    facts = gather(system)
    client = facts.client
    print(json.dumps(assemble_status(client, None, status_update(system, client['version']),
                                     live_job(system), system.now(), installed=facts.installed)))
    return 0
