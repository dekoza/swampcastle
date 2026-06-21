"""CLI internal / hidden command handlers: hook, instructions, ni."""

from swampcastle.cli.commands.shared import _settings


def cmd_hook(args):
    from swampcastle.hooks_cli import run_hook

    run_hook(args.hook, args.harness)


def cmd_instructions(args):
    from swampcastle.instructions_cli import run_instructions

    run_instructions(args.name)
