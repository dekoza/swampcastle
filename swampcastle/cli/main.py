"""SwampCastle CLI — argparse setup + dispatch."""

import argparse
import os
import sys

from swampcastle.version import __version__


def _hide_subparser(subparsers, *hidden_names: str) -> None:
    """Hide internal subcommands from argparse help output.

    argparse does not support hidden subparsers properly: using
    help=argparse.SUPPRESS on add_parser() still renders '==SUPPRESS==' in the
    command list. To hide a subparser, we must remove its pseudo-action from
    _choices_actions and rebuild the metavar used in the usage line.
    """
    hidden = set(hidden_names)
    subparsers._choices_actions = [
        action for action in subparsers._choices_actions if action.dest not in hidden
    ]
    visible_names = [name for name in subparsers._name_parser_map if name not in hidden]
    subparsers.metavar = "{" + ",".join(visible_names) + "}"


def _require_internal_access(command: str) -> None:
    """Require an explicit env guard for internal commands."""
    if os.environ.get("SWAMPCASTLE_INTERNAL") == "1":
        return
    print(
        f"  Error: '{command}' is an internal command. "
        "Set SWAMPCASTLE_INTERNAL=1 if you intentionally need it."
    )
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser(
        prog="swampcastle",
        description='SwampCastle — "The fourth one stayed up."',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--palace", "--castle", default=None, dest="palace", help="Path to castle directory"
    )
    parser.add_argument(
        "--backend",
        choices=["lance", "postgres", "chroma"],
        default=None,
        help="Storage backend override",
    )
    parser.add_argument("--version", action="version", version=f"swampcastle {__version__}")

    sub = parser.add_subparsers(dest="command")

    # project
    p = sub.add_parser(
        "project",
        help="Create or update project-local mining config (.swampcastle.yaml)",
    )
    p.add_argument("dir", help="Project directory")
    p.add_argument("--yes", action="store_true", help="Auto-accept without prompts")
    p.add_argument("--wing", default=None, help="Override wing name")
    p.add_argument("--team", nargs="*", default=None, help="Team member identifiers")

    # wizard
    sub.add_parser("wizard", help="Configure global runtime settings")

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
    p.add_argument(
        "--extract-kg-proposals",
        action="store_true",
        help="After ingest, extract candidate triples into the KG proposal store (proposal-only, opt-in).",
    )
    p.add_argument(
        "--explain", action="store_true", help="Print skip reasons for files during mining"
    )

    # seek (search)
    p = sub.add_parser("seek", aliases=["search"], help="Seek anything in the castle")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--wing", default=None)
    p.add_argument("--room", default=None)
    p.add_argument("--contributor", default=None)
    p.add_argument("--results", type=int, default=5)

    p = sub.add_parser("survey", aliases=["status"], help="Survey the castle")

    # deskeleton
    p = sub.add_parser(
        "deskeleton",
        help="Identify and replace skeleton drawers with full implementations",
    )
    p.add_argument("--wing", default=None, help="Filter by wing")
    p.add_argument("--room", default=None, help="Filter by room")
    p.add_argument("--dry-run", action="store_true", help="Show what would be deskeletonized")

    # drawbridge (mcp)
    p_db = sub.add_parser("drawbridge", aliases=["mcp"], help="Lower the drawbridge — MCP server")
    db_sub = p_db.add_subparsers(dest="mcp_action")
    p_dbr = db_sub.add_parser("run", help="Start MCP server (JSON-RPC stdin/stdout)")
    p_dbr.add_argument("--palace", dest="run_palace", default=None)

    # herald (wake-up)
    sub.add_parser("herald", aliases=["wake-up"], help="Sound the herald — protocol")

    # brief (minstrel)
    p = sub.add_parser("brief", aliases=["minstrel"], help="Tell the story of a wing")
    p.add_argument("--wing", required=True)

    # cleave (split)
    p = sub.add_parser("cleave", aliases=["split"], help="Cleave mega-files into sessions")
    p.add_argument("dir")
    p.add_argument("--output-dir", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--min-sessions", type=int, default=2)

    # distill (compress)
    p = sub.add_parser("distill", aliases=["compress"], help="Distill using AAAK dialect")
    p.add_argument("--wing", help="Filter by wing")
    p.add_argument("--room", help="Filter by room")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--apply",
        action="store_true",
        help="Persist AAAK metadata updates. Without this flag distill runs in preview mode.",
    )
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
    for n in ["project", "search", "mine", "help", "status"]:
        instr_sub.add_parser(n)

    # raise (migrate)
    p = sub.add_parser(
        "raise", aliases=["migrate"], help="Raise from the swamp (ChromaDB → LanceDB)"
    )
    p.add_argument("--source-palace", default=None, help="Path to legacy ChromaDB palace directory")
    p.add_argument("--target-castle", default=None, help="Path to target castle directory")
    p.add_argument("--dry-run", action="store_true")

    # reforge (reindex)
    p = sub.add_parser("reforge", aliases=["reindex"], help="Reforge embeddings with new model")
    p.add_argument("--wing", help="Filter by wing")
    p.add_argument("--room", help="Filter by room")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--embedder", default=None)
    p.add_argument("--device", default=None)

    # armory (embedders)
    sub.add_parser("armory", aliases=["embedders"], help="List available embedding models")

    # kg proposal review
    p_kg = sub.add_parser("kg", help="Review and manage KG candidate triples")
    kg_sub = p_kg.add_subparsers(dest="kg_action")

    p = kg_sub.add_parser("extract", help="Extract candidate triples from drawers")
    p.add_argument("--wing", default=None)
    p.add_argument("--room", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--apply",
        action="store_true",
        help="Persist extracted candidate triples. Without this flag extraction runs in preview mode.",
    )
    p.add_argument("--limit", type=int, default=0)

    p = kg_sub.add_parser("review", help="List candidate triples")
    p.add_argument("--status", choices=["proposed", "accepted", "rejected"], default=None)
    p.add_argument("--predicate", default=None)
    p.add_argument("--min-confidence", dest="min_confidence", type=float, default=None)
    p.add_argument("--wing", default=None)
    p.add_argument("--room", default=None)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument(
        "--conflicts-only",
        action="store_true",
        help="Show only proposals that conflict with currently-active exclusive facts",
    )

    p = kg_sub.add_parser("accept", help="Accept a candidate triple into the KG")
    p.add_argument("candidate_id")
    p.add_argument("--subject", default=None)
    p.add_argument("--predicate", default=None)
    p.add_argument("--object", default=None)
    p.add_argument("--valid-from", dest="valid_from", default=None)
    p.add_argument("--valid-to", dest="valid_to", default=None)
    p.add_argument(
        "--invalidate-conflicts",
        action="store_true",
        help="Invalidate current conflicting facts for exclusive predicates before accepting",
    )

    p = kg_sub.add_parser("reject", help="Reject a candidate triple")
    p.add_argument("candidate_id")

    # garrison (serve)
    p = sub.add_parser("garrison", aliases=["serve"], help="Man the garrison (sync server)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=7433)

    # parley (sync)
    p = sub.add_parser("parley", aliases=["sync"], help="Parley with remote castle (sync)")
    p.add_argument("--server", required=True)
    p.add_argument("--dry-run", action="store_true")

    # ni
    sub.add_parser("ni", help=argparse.SUPPRESS)

    # argparse does not hide subparsers correctly with help=SUPPRESS.
    # Remove internal/easter-egg commands from the visible help listing.
    _hide_subparser(sub, "hook", "instructions", "ni")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    from swampcastle.cli import commands as cmd
    from swampcastle.runtime_config import ensure_runtime_config

    # Two-level subcommands
    if args.command in ("drawbridge", "mcp"):
        if getattr(args, "mcp_action", None) == "run":
            cmd.cmd_drawbridge_run(args)
        else:
            cmd.cmd_drawbridge_setup(args)
        return

    if args.command == "kg":
        action = getattr(args, "kg_action", None)
        if not action:
            p_kg.print_help()
            return
        if action == "extract":
            cmd.cmd_kg_extract(args)
        elif action == "review":
            cmd.cmd_kg_review(args)
        elif action == "accept":
            cmd.cmd_kg_accept(args)
        elif action == "reject":
            cmd.cmd_kg_reject(args)
        return

    if args.command == "hook":
        _require_internal_access("hook")
        if not getattr(args, "hook_action", None):
            p_hook.print_help()
            return
        cmd.cmd_hook(args)
        return

    if args.command == "instructions":
        _require_internal_access("instructions")
        name = getattr(args, "instructions_name", None)
        if not name:
            p_instr.print_help()
            return
        args.name = name
        cmd.cmd_instructions(args)
        return

    if args.command != "ni":
        ensure_runtime_config()

    dispatch = {
        "project": cmd.cmd_project,
        "wizard": cmd.cmd_wizard,
        "gather": cmd.cmd_gather,
        "mine": cmd.cmd_gather,
        "seek": cmd.cmd_seek,
        "search": cmd.cmd_seek,
        "survey": cmd.cmd_survey,
        "status": cmd.cmd_survey,
        "herald": cmd.cmd_herald,
        "wake-up": cmd.cmd_herald,
        "brief": cmd.cmd_brief,
        "minstrel": cmd.cmd_brief,
        "cleave": cmd.cmd_cleave,
        "split": cmd.cmd_cleave,
        "distill": cmd.cmd_distill,
        "compress": cmd.cmd_distill,
        "raise": cmd.cmd_raise,
        "migrate": cmd.cmd_raise,
        "reforge": cmd.cmd_reforge,
        "reindex": cmd.cmd_reforge,
        "armory": cmd.cmd_armory,
        "embedders": cmd.cmd_armory,
        "garrison": cmd.cmd_garrison,
        "serve": cmd.cmd_garrison,
        "parley": cmd.cmd_parley,
        "sync": cmd.cmd_parley,
        "ni": cmd.cmd_ni,
        "deskeleton": cmd.cmd_deskeleton,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
