"""SwampCastle CLI — argparse setup + dispatch."""

import argparse
import sys

from swampcastle.version import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="swampcastle",
        description='SwampCastle — "The fourth one stayed up."',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--palace", "--castle", default=None, dest="palace",
                        help="Path to castle directory")
    parser.add_argument(
        "--backend",
        choices=["lance", "postgres", "chroma"],
        default=None,
        help="Storage backend override",
    )
    parser.add_argument("--version", action="version", version=f"swampcastle {__version__}")

    sub = parser.add_subparsers(dest="command")

    # build (init)
    p = sub.add_parser("build", aliases=["init"], help="Build your castle from a project directory")
    p.add_argument("dir", help="Project directory")
    p.add_argument("--yes", action="store_true", help="Auto-accept detected entities")

    # gather (mine)
    p = sub.add_parser("gather", aliases=["mine"], help="Gather files into the castle")
    p.add_argument("dir", help="Directory to gather")
    p.add_argument("--mode", choices=["projects", "convos"], default="projects")
    p.add_argument("--wing", default=None)
    p.add_argument("--no-gitignore", action="store_true")
    p.add_argument("--include-ignored", action="append", default=[])
    p.add_argument("--agent", default="swampcastle")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--extract", choices=["exchange", "general"], default="exchange")

    # seek (search)
    p = sub.add_parser("seek", aliases=["search"], help="Seek anything in the castle")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--wing", default=None)
    p.add_argument("--room", default=None)
    p.add_argument("--results", type=int, default=5)

    # survey (status)
    sub.add_parser("survey", aliases=["status"], help="Survey the castle")

    # drawbridge (mcp)
    p_db = sub.add_parser("drawbridge", aliases=["mcp"],
                          help="Lower the drawbridge — MCP server")
    db_sub = p_db.add_subparsers(dest="mcp_action")
    p_dbr = db_sub.add_parser("run", help="Start MCP server (JSON-RPC stdin/stdout)")
    p_dbr.add_argument("--palace", dest="run_palace", default=None)

    # herald (wake-up)
    p = sub.add_parser("herald", aliases=["wake-up"], help="Sound the herald — L0+L1 context")
    p.add_argument("--wing", default=None)

    # cleave (split)
    p = sub.add_parser("cleave", aliases=["split"], help="Cleave mega-files into sessions")
    p.add_argument("dir")
    p.add_argument("--output-dir", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--min-sessions", type=int, default=2)

    # distill (compress)
    p = sub.add_parser("distill", aliases=["compress"], help="Distill using AAAK dialect")
    p.add_argument("--wing", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--config", default=None)

    # hook (internal)
    p_hook = sub.add_parser("hook", help=argparse.SUPPRESS)
    hook_sub = p_hook.add_subparsers(dest="hook_action")
    p_hr = hook_sub.add_parser("run")
    p_hr.add_argument("--hook", required=True, choices=["session-start", "stop", "precompact"])
    p_hr.add_argument("--harness", required=True, choices=["claude-code", "codex"])

    # instructions (internal)
    p_instr = sub.add_parser("instructions", help=argparse.SUPPRESS)
    instr_sub = p_instr.add_subparsers(dest="instructions_name")
    for n in ["init", "search", "mine", "help", "status"]:
        instr_sub.add_parser(n)

    # raise (migrate)
    p = sub.add_parser("raise", aliases=["migrate"], help="Raise from the swamp (ChromaDB → LanceDB)")
    p.add_argument("--source-palace", default=None, help="Path to legacy ChromaDB palace directory")
    p.add_argument("--target-castle", default=None, help="Path to target castle directory")
    p.add_argument("--dry-run", action="store_true")

    # reforge (reindex)
    p = sub.add_parser("reforge", aliases=["reindex"], help="Reforge embeddings with new model")
    p.add_argument("--embedder", default=None)
    p.add_argument("--device", default=None)
    p.add_argument("--dry-run", action="store_true")

    # armory (embedders)
    sub.add_parser("armory", aliases=["embedders"], help="List available embedding models")

    # garrison (serve)
    p = sub.add_parser("garrison", aliases=["serve"], help="Man the garrison (sync server)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=7433)

    # parley (sync)
    p = sub.add_parser("parley", aliases=["sync"], help="Parley with remote castle (sync)")
    p.add_argument("--server", required=True)
    p.add_argument("--auto", action="store_true")
    p.add_argument("--interval", type=int, default=300)
    p.add_argument("--dry-run", action="store_true")

    # ni
    sub.add_parser("ni", help=argparse.SUPPRESS)

    args, _ = parser.parse_known_args()

    if not args.command:
        parser.print_help()
        return

    from swampcastle.cli import commands as cmd

    # Two-level subcommands
    if args.command in ("drawbridge", "mcp"):
        if getattr(args, "mcp_action", None) == "run":
            cmd.cmd_drawbridge_run(args)
        else:
            cmd.cmd_drawbridge_setup(args)
        return

    if args.command == "hook":
        if not getattr(args, "hook_action", None):
            p_hook.print_help()
            return
        cmd.cmd_hook(args)
        return

    if args.command == "instructions":
        name = getattr(args, "instructions_name", None)
        if not name:
            p_instr.print_help()
            return
        args.name = name
        cmd.cmd_instructions(args)
        return

    dispatch = {
        "build": cmd.cmd_build, "init": cmd.cmd_build,
        "gather": cmd.cmd_gather, "mine": cmd.cmd_gather,
        "seek": cmd.cmd_seek, "search": cmd.cmd_seek,
        "survey": cmd.cmd_survey, "status": cmd.cmd_survey,
        "herald": cmd.cmd_herald, "wake-up": cmd.cmd_herald,
        "cleave": cmd.cmd_cleave, "split": cmd.cmd_cleave,
        "distill": cmd.cmd_distill, "compress": cmd.cmd_distill,
        "raise": cmd.cmd_raise, "migrate": cmd.cmd_raise,
        "reforge": cmd.cmd_reforge, "reindex": cmd.cmd_reforge,
        "armory": cmd.cmd_armory, "embedders": cmd.cmd_armory,
        "garrison": cmd.cmd_garrison, "serve": cmd.cmd_garrison,
        "parley": cmd.cmd_parley, "sync": cmd.cmd_parley,
        "ni": cmd.cmd_ni,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
