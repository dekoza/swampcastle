"""CLI command handlers — each creates a Castle and calls services."""

import os
import shlex
import sys
from pathlib import Path

from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings


def _print_section(title: str) -> None:
    print(f"  SwampCastle {title}")


def _print_kv(label: str, value) -> None:
    print(f"  {label}: {value}")


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
        _print_section("Survey")
        _print_kv("Drawers", s.total_drawers)
        if s.wings:
            _print_kv("Wings", ", ".join(sorted(s.wings.keys())))
        if s.rooms:
            _print_kv("Rooms", ", ".join(sorted(s.rooms.keys())))


def cmd_seek(args):
    from swampcastle.castle import Castle
    from swampcastle.models import SearchQuery

    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        result = castle.search.search(
            SearchQuery(
                query=args.query,
                wing=args.wing,
                room=args.room,
                limit=args.results,
            )
        )
        _print_section("Seek")
        _print_kv("Query", args.query or "")
        if args.wing:
            _print_kv("Wing", args.wing)
        if args.room:
            _print_kv("Room", args.room)
        if not result.results:
            print("  No results found.")
            return
        _print_kv("Results", len(result.results))
        for i, hit in enumerate(result.results, 1):
            print(f"\n  [{i}] {hit.wing} / {hit.room}  (match: {hit.similarity})")
            print(f"      {hit.text[:200]}")


def cmd_build(args):
    from swampcastle.entity_detector import confirm_entities, detect_entities, scan_for_detection
    from swampcastle.mining.rooms import detect_rooms_local

    project_dir = os.path.expanduser(args.dir)
    if not os.path.isdir(project_dir):
        print(f"  Error: {project_dir} is not a directory")
        sys.exit(1)

    detect_rooms_local(project_dir, yes=args.yes)

    candidates = scan_for_detection(project_dir)
    if candidates:
        entities = detect_entities(candidates)
        if not args.yes:
            entities = confirm_entities(entities)
        print(
            f"  Detected {len(entities.get('people', []))} people, "
            f"{len(entities.get('projects', []))} projects"
        )


def cmd_gather(args):
    settings = _settings(args)
    palace_path = str(settings.castle_path)
    project_dir = os.path.expanduser(args.dir)
    storage_factory = None
    if not args.dry_run:
        storage_factory = factory_from_settings(settings)

    _print_section("Gather")
    _print_kv("Mode", args.mode)
    _print_kv("Source", project_dir)
    _print_kv("Castle", palace_path)
    if args.wing:
        _print_kv("Wing", args.wing)

    if args.mode == "convos":
        from swampcastle.mining.convo import mine_convos

        mine_convos(
            project_dir,
            palace_path,
            wing=args.wing,
            agent=args.agent,
            dry_run=args.dry_run,
            extract_mode=args.extract,
            limit=args.limit,
            storage_factory=storage_factory,
        )
    else:
        from swampcastle.mining.miner import mine

        mine(
            project_dir,
            palace_path,
            wing=args.wing,
            agent=args.agent,
            respect_gitignore=not args.no_gitignore,
            include_ignored=args.include_ignored,
            dry_run=args.dry_run,
            limit=args.limit,
            storage_factory=storage_factory,
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

    argv = [args.dir]
    if args.output_dir:
        argv.extend(["--output-dir", args.output_dir])
    if args.dry_run:
        argv.append("--dry-run")
    if args.min_sessions:
        argv.extend(["--min-sessions", str(args.min_sessions)])
    split_main(argv)


def cmd_distill(args):
    from swampcastle.castle import Castle
    from swampcastle.storage import factory_from_settings

    settings = _settings(args)

    config_path = getattr(args, "config", None)

    with Castle(settings, factory_from_settings(settings)) as castle:
        count = castle.vault.distill(
            wing=args.wing,
            room=args.room,
            dry_run=args.dry_run,
            config_path=config_path,
        )
        if count == 0:
            print("  No drawers to distill.")
            return

        if args.dry_run:
            print(f"  DRY RUN — would distill {count} drawers.")
        else:
            print(f"  Distilled {count} drawers with AAAK dialect.")


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

    run_hook(args.hook, args.harness)


def cmd_instructions(args):
    from swampcastle.instructions_cli import run_instructions

    run_instructions(args.name)


def cmd_raise(args):
    from swampcastle.migrate import migrate

    target_castle = getattr(args, "target_castle", None) or getattr(args, "palace", None)
    migrate(
        source_palace=getattr(args, "source_palace", None),
        target_castle=target_castle,
        dry_run=getattr(args, "dry_run", False),
    )


def cmd_reforge(args):
    from swampcastle.castle import Castle
    from swampcastle.storage import factory_from_settings

    settings = _settings(args)

    # Override embedder settings if specified
    embedder = getattr(args, "embedder", None)
    device = getattr(args, "device", None)
    if embedder:
        settings.embedder = embedder
    if device:
        settings.embedder_device = device

    with Castle(settings, factory_from_settings(settings)) as castle:
        count = castle.vault.reforge(
            wing=args.wing,
            room=args.room,
            dry_run=args.dry_run,
        )
        if count == 0:
            print("  No drawers to reforge.")
            return

        if args.dry_run:
            print(f"  DRY RUN — would reforge {count} drawers.")
        else:
            embedder_info = embedder or settings.embedder
            print(f"  Reforged {count} drawers with {embedder_info} embedder.")


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
        identity = NodeIdentity(config_dir=str(settings.config_dir))
        vv_path = os.path.join(str(settings.castle_path), "version_vector.json")
        engine = SyncEngine(castle._collection, identity=identity, vv_path=vv_path)
        client = SyncClient(args.server)
        _print_section("Sync")
        _print_kv("Server", args.server)
        _print_kv("Castle", settings.castle_path)
        if args.dry_run:
            print("  DRY RUN — no changes.")
            return
        result = client.sync(engine)
        _print_kv("Pushed", result.get("push", {}).get("sent", 0))
        _print_kv("Pulled", result.get("pull", {}).get("received", 0))


def cmd_ni(args):
    print("\n  We are the Knights who say... Ni!")
    print("  Bring us a shrubbery! (Or run: swampcastle build <dir>)\n")
