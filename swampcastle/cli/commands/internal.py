"""CLI internal / hidden command handlers: hook, instructions, ni."""



def cmd_hook(args):
    if getattr(args, "hook_action", "run") == "refresh-digest":
        from swampcastle.hooks_cli import refresh_digest_cache

        refresh_digest_cache(args.project_dir)
        return

    from swampcastle.hooks_cli import run_hook

    run_hook(args.hook, args.harness)


def cmd_instructions(args):
    from swampcastle.instructions_cli import run_instructions

    run_instructions(args.name)
