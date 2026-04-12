"""SwampCastle CLI — thin dispatcher over services."""

import argparse
import sys

from swampcastle.version import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="swampcastle",
        description='SwampCastle — "The fourth one stayed up."',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--palace", default=None, help="Path to castle directory")
    parser.add_argument("--version", action="version", version=f"swampcastle {__version__}")

    sub = parser.add_subparsers(dest="command")

    # survey (status)
    sub.add_parser("survey", aliases=["status"], help="Survey the castle")

    # drawbridge (MCP)
    p_drawbridge = sub.add_parser(
        "drawbridge", aliases=["mcp"],
        help="Lower the drawbridge — run the MCP server or show setup",
    )
    db_sub = p_drawbridge.add_subparsers(dest="mcp_action")
    p_db_run = db_sub.add_parser("run", help="Start MCP server (JSON-RPC stdin/stdout)")
    p_db_run.add_argument("--palace", dest="run_palace", default=None)

    # seek (search)
    p_seek = sub.add_parser("seek", aliases=["search"], help="Search the castle")
    p_seek.add_argument("query", nargs="?", default="")
    p_seek.add_argument("--wing", default=None)
    p_seek.add_argument("--room", default=None)
    p_seek.add_argument("--results", type=int, default=5)

    args, unknown = parser.parse_known_args()

    if not args.command:
        parser.print_help()
        return

    if args.command in ("drawbridge", "mcp"):
        if getattr(args, "mcp_action", None) == "run":
            _cmd_drawbridge_run(args)
        else:
            _cmd_drawbridge_setup(args)
        return

    if args.command in ("survey", "status"):
        _cmd_survey(args)
        return

    if args.command in ("seek", "search"):
        _cmd_seek(args)
        return

    parser.print_help()


def _cmd_survey(args):
    from swampcastle.castle import Castle
    from swampcastle.settings import CastleSettings
    from swampcastle.storage.memory import InMemoryStorageFactory

    settings = _make_settings(args)
    factory = _make_factory(settings)
    with Castle(settings, factory) as castle:
        status = castle.catalog.status()
        print(f"  SwampCastle — {status.total_drawers} drawers")
        if status.wings:
            print(f"  Wings: {', '.join(sorted(status.wings.keys()))}")
        if status.rooms:
            print(f"  Rooms: {', '.join(sorted(status.rooms.keys()))}")


def _cmd_seek(args):
    from swampcastle.castle import Castle
    from swampcastle.models import SearchQuery
    from swampcastle.settings import CastleSettings

    settings = _make_settings(args)
    factory = _make_factory(settings)
    with Castle(settings, factory) as castle:
        result = castle.search.search(SearchQuery(
            query=args.query, wing=args.wing, room=args.room, limit=args.results,
        ))
        if not result.results:
            print("  No results found.")
            return
        for i, hit in enumerate(result.results, 1):
            print(f"\n  [{i}] {hit.wing} / {hit.room}  (match: {hit.similarity})")
            print(f"      {hit.text[:200]}")


def _cmd_drawbridge_setup(args):
    base_cmd = "swampcastle drawbridge run"
    palace = getattr(args, "palace", None)
    if palace:
        import shlex
        from pathlib import Path
        resolved = str(Path(palace).expanduser())
        cmd = f"{base_cmd} --palace {shlex.quote(resolved)}"
    else:
        cmd = base_cmd

    print("SwampCastle MCP setup:")
    print(f"  claude mcp add swampcastle -- {cmd}")
    print(f"\nRun directly:\n  {cmd}")
    if not palace:
        print(f"\nWith custom castle:\n  {base_cmd} --palace /path/to/castle")


def _cmd_drawbridge_run(args):
    import os
    from pathlib import Path
    palace = getattr(args, "run_palace", None) or getattr(args, "palace", None)
    if palace:
        os.environ["SWAMPCASTLE_CASTLE_PATH"] = str(Path(palace).expanduser().resolve())
    from swampcastle.mcp.server import main as mcp_main
    mcp_main()


def _make_settings(args):
    from swampcastle.settings import CastleSettings
    kwargs = {}
    if getattr(args, "palace", None):
        kwargs["castle_path"] = args.palace
    return CastleSettings(_env_file=None, **kwargs)


def _make_factory(settings):
    """Create storage factory — try LanceDB, fall back to InMemory."""
    try:
        from swampcastle.storage.lance import LocalStorageFactory
        return LocalStorageFactory(settings.castle_path)
    except (ImportError, Exception):
        from swampcastle.storage.memory import InMemoryStorageFactory
        return InMemoryStorageFactory()
