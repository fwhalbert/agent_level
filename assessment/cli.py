"""Unified public entrypoint; assessment and recording retain their own parsers."""
import argparse
import sys

import assess
import agent_level_record


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog='agent-level',
        description='Agent Level — measure AI engineering workflow autonomy from local evidence.',
        epilog='With no subcommand, assess runs in the current project. Use COMMAND --help for options. '
               'Legacy agent-level-assess and agent-level-record commands remain available.',
    )
    parser.add_argument('--version', action='version', version=assess.VERSION)
    commands = parser.add_subparsers(title='commands', dest='command')
    commands.add_parser('assess', help='Analyze local activity and generate an offline report')
    commands.add_parser('record', help='Register acceptance, record human review, or locate task evidence')
    commands.add_parser('compare', help='Open the existing before/after evidence comparison view')
    commands.add_parser('setup', help='Reference this checkout in Codex global instructions')
    if args and args[0] in ('-h', '--help', '--version'):
        parser.parse_args(args)
        return 0
    command = 'assess'
    if args and not args[0].startswith('-'):
        command = args.pop(0)
        if command not in ('assess', 'record', 'compare', 'setup'):
            parser.error(f'unknown command: {command}')
    if command == 'record':
        return agent_level_record.main(args)
    if command == 'setup':
        from bootstrap import setup_main
        return setup_main(args)
    return assess.project_cli(
        ['--report-name', 'Agent Level', *args],
        default_method='improvement' if command == 'compare' else 'levels',
    )


if __name__ == '__main__':
    raise SystemExit(main())
