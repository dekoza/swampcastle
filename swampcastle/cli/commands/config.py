"""CLI command handlers — config / setup (wizard, tune, drawbridge)."""

import os
import shlex
import sys
from pathlib import Path

from swampcastle.cli.commands.shared import _settings


# ═══════════════════════════════════════════════════════════════════════
# Region: Config / setup (wizard, tune, project, drawbridge)
# ═══════════════════════════════════════════════════════════════════════

def cmd_wizard(args):
    from swampcastle.wizard import run_wizard

    run_wizard()


def cmd_tune(args):
    from swampcastle.wizard import run_tune

    run_tune()


# ───────────────────────────────────────────────────────────────────────
# MCP server
# ───────────────────────────────────────────────────────────────────────

def cmd_drawbridge_setup(args):
    base_cmd = "swampcastle drawbridge run"
    palace = getattr(args, "palace", None)
    if palace:
        resolved = str(Path(palace).expanduser())
        cmd = f"{base_cmd} --palace {shlex.quote(resolved)}"
    else:
        cmd = base_cmd
    print("SwampCastle MCP setup:")
    print(f"  claude mcp add swampcastle -- {cmd}")
    print(f"\nRun directly:\n  {cmd}")
    if not palace:
        print(f"\nWith custom castle:\n  {base_cmd} --palace /path/to/castle")


def cmd_drawbridge_run(args):
    palace = getattr(args, "run_palace", None) or getattr(args, "palace", None)
    if palace:
        os.environ["SWAMPCASTLE_CASTLE_PATH"] = str(Path(palace).expanduser().resolve())
    from swampcastle.mcp.server import main as mcp_main

    mcp_main()
