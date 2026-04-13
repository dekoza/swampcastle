"""CLI command handlers — each creates a Castle and calls services."""

import os
import shlex
import sys
from pathlib import Path

from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings


def _settings(args) -> CastleSettings:
    kwargs = {}
    palace = getattr(args, "palace", None)
    if palace:
        kwargs["castle_path"] = palace
    backend = getattr(args, "backend", None)
    if backend:
        kwargs["backend"] = backend
    return CastleSettings(_env_file=None, **kwargs)


def cmd_survey(args):
    from swampcastle.castle import Castle
    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        s = castle.catalog.status()
        print(f"  SwampCastle — {s.total_drawers} drawers")
        if s.wings:
            print(f"  Wings: {', '.join(sorted(s.wings.keys()))}")
        if s.rooms:
            print(f"  Rooms: {', '.join(sorted(s.rooms.keys()))}")


def cmd_seek(args):
    from swampcastle.castle import Castle
    from swampcastle.models import SearchQuery
    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        result = castle.search.search(SearchQuery(
            query=args.query, wing=args.wing, room=args.room, limit=args.results,
        ))
        if not result.results:
            print("  No results found.")
            return
        for i, hit in enumerate(result.results, 1):
            print(f"\n  [{i}] {hit.wing} / {hit.room}  (match: {hit.similarity})")
            print(f"      {hit.text[:200]}")


def cmd_build(args):
    from swampcastle.entity_detector import scan_for_detection, detect_entities, confirm_entities
    from swampcastle.mining.rooms import detect_rooms_from_folders

    project_dir = os.path.expanduser(args.dir)
    if not os.path.isdir(project_dir):
        print(f"  Error: {project_dir} is not a directory")
        sys.exit(1)

    settings = _settings(args)
    rooms = detect_rooms_from_folders(project_dir, auto_accept=args.yes)
    print(f"  Detected {len(rooms)} rooms in {project_dir}")

    candidates = scan_for_detection(project_dir)
    if candidates:
        entities = detect_entities(candidates)
        if not args.yes:
            entities = confirm_entities(entities)
        print(f"  Detected {len(entities.get('people', []))} people, "
              f"{len(entities.get('projects', []))} projects")


def cmd_gather(args):
    settings = _settings(args)
    palace_path = str(settings.castle_path)
    project_dir = os.path.expanduser(args.dir)

    if args.mode == "convos":
        from swampcastle.mining.convo import mine_convos
        mine_convos(
            project_dir, palace_path,
            wing=args.wing, agent=args.agent,
            dry_run=args.dry_run, extract_mode=args.extract,
            limit=args.limit,
        )
    else:
        from swampcastle.mining.miner import mine
        mine(
            project_dir, palace_path,
            wing=args.wing, agent=args.agent,
            no_gitignore=args.no_gitignore,
            include_ignored=args.include_ignored,
            dry_run=args.dry_run, limit=args.limit,
        )


def cmd_herald(args):
    """Wake-up context (L0+L1)."""
    from swampcastle.castle import Castle
    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        s = castle.catalog.status()
        print(s.protocol)
        if s.wings:
            print(f"\nWings: {', '.join(sorted(s.wings.keys()))}")
            print(f"Total: {s.total_drawers} drawers")


def cmd_cleave(args):
    from swampcastle.split_mega_files import main as split_main
    sys.argv = ["swampcastle", args.dir]
    if args.output_dir:
        sys.argv.extend(["--output-dir", args.output_dir])
    if args.dry_run:
        sys.argv.append("--dry-run")
    if args.min_sessions:
        sys.argv.extend(["--min-sessions", str(args.min_sessions)])
    split_main()


def cmd_distill(args):
    from swampcastle.dialect import Dialect
    settings = _settings(args)
    palace_path = str(settings.castle_path)

    config_path = args.config
    if not config_path:
        for candidate in ["entities.json", os.path.join(palace_path, "entities.json")]:
            if os.path.exists(candidate):
                config_path = candidate
                break

    dialect = Dialect.from_config(config_path) if config_path else Dialect()

    from swampcastle.castle import Castle
    with Castle(settings, factory_from_settings(settings)) as castle:
        s = castle.catalog.status()
        if s.total_drawers == 0:
            print("  No drawers to distill.")
            return
        print(f"  Distilling {s.total_drawers} drawers...")
        if args.dry_run:
            print("  DRY RUN — no changes.")


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


def cmd_hook(args):
    from swampcastle.hooks_cli import run_hook
    run_hook(args)


def cmd_instructions(args):
    from swampcastle.instructions_cli import run_instructions
    run_instructions(args)


def cmd_raise(args):
    print("  Migration: ChromaDB → LanceDB")
    print("  Install chromadb: pip install 'swampcastle[chroma]'")
    print("  Then run: swampcastle raise")


def cmd_reforge(args):
    from swampcastle.embeddings import get_embedder, list_embedders
    settings = _settings(args)
    if args.dry_run:
        print("  DRY RUN — would re-embed all drawers")
        return
    print("  Reforging embeddings...")
    print(f"  Embedder: {args.embedder or 'default'}")


def cmd_armory(args):
    from swampcastle.embeddings import list_embedders
    models = list_embedders()
    print("  Available embedding models:")
    for name, info in models.items():
        print(f"    {name}: {info}")


def cmd_garrison(args):
    try:
        import uvicorn
    except ImportError:
        print("  Sync server requires: pip install 'swampcastle[server]'")
        sys.exit(1)

    from swampcastle.sync_server import create_app
    settings = _settings(args)
    os.environ["SWAMPCASTLE_CASTLE_PATH"] = str(settings.castle_path)
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)


def cmd_parley(args):
    from swampcastle.castle import Castle
    from swampcastle.sync import SyncEngine
    from swampcastle.sync_client import SyncClient
    from swampcastle.sync_meta import NodeIdentity

    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        identity = NodeIdentity()
        vv_path = os.path.join(str(settings.castle_path), "version_vector.json")
        engine = SyncEngine(castle._collection, identity=identity, vv_path=vv_path)
        client = SyncClient(args.server)
        print(f"  Syncing with {args.server}...")
        if args.dry_run:
            print("  DRY RUN — no changes.")
            return
        result = client.sync(engine)
        print(f"  Done. Pushed: {result.get('push', {}).get('sent', 0)}, "
              f"Pulled: {result.get('pull', {}).get('received', 0)}")


def cmd_ni(args):
    print("\n  We are the Knights who say... Ni!")
    print("  Bring us a shrubbery! (Or run: swampcastle build <dir>)\n")
