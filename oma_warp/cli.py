"""Public backend entry point."""
import argparse
import json
from .client import gather
from .connection import switch
from .probe import cached_probe, invalidate, probe_status
from .jobs import live_job, start
from .status import assemble_status
from .system import System
from .uninstall import uninstall
from .update import check, status_update


def main(argv=None, *, system=None):
    parser = argparse.ArgumentParser(prog='oma-warp')
    sub = parser.add_subparsers(dest='command', required=True)
    status = sub.add_parser('status')
    status.add_argument('--json', action='store_true')
    status.add_argument('--probe', action='store_true')
    check_parser = sub.add_parser('check')
    check_parser.add_argument('--json', action='store_true')
    sub.add_parser('connect')
    sub.add_parser('disconnect')
    sub.add_parser('reconnect')
    sub.add_parser('uninstall')
    job = sub.add_parser('start')
    job.add_argument('--job-id', required=True)
    args = parser.parse_args(argv)
    system = system if system is not None else System()
    if args.command == 'check':
        document = check(system)
        print(json.dumps(document) if args.json else
              f"Latest verified release: {document['latest']}\nVerified at: {document['verified_at']}" +
              (f"\nCheck failed: {document['last_error']}" if document['last_error'] else ''))
        return int(document['last_error'] is not None)
    if args.command in ('connect', 'disconnect', 'reconnect'):
        invalidate(system)
        if args.command == 'reconnect':
            return switch(system, 'disconnect') or switch(system, 'connect')
        return switch(system, args.command)
    if args.command == 'start':
        return start(system, args.job_id)
    if args.command == 'uninstall':
        return uninstall(system)
    if args.probe:
        facts, probe = probe_status(system)
    else:
        facts = gather(system)
        probe = cached_probe(system, facts)
    client = facts.client
    print(json.dumps(assemble_status(client, probe, status_update(system, client['version']),
                                     live_job(system), system.now(), facts.operation_mode)))
    return 0
