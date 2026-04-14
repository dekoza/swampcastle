"""CLI command handlers — each creates a Castle and calls services."""

import os
import shlex
import sqlite3
import sys
import tempfile
from pathlib import Path

from swampcastle.project_config import resolve_project_config
from swampcastle.runtime_config import ensure_runtime_config
from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings


DESKELETON_BATCH_SIZE = 1000


class DeskeletonTargetStore:
    """SQLite-backed temporary store for unique deskeleton targets."""

    def __init__(self, path: str | Path):
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deskeleton_targets (
                wing TEXT NOT NULL,
                source_file TEXT NOT NULL,
                PRIMARY KEY (wing, source_file)
            )
            """
        )

    def add(self, wing: str, source_file: str) -> bool:
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO deskeleton_targets (wing, source_file) VALUES (?, ?)",
            (wing, source_file),
        )
        return cursor.rowcount == 1

    def count(self) -> int:
        self._conn.commit()
        row = self._conn.execute("SELECT COUNT(*) FROM deskeleton_targets").fetchone()
        return int(row[0] if row is not None else 0)

    def iter_targets(self):
        self._conn.commit()
        cursor = self._conn.execute(
            "SELECT wing, source_file FROM deskeleton_targets ORDER BY wing, source_file"
        )
        yield from cursor

    def close(self) -> None:
        self._conn.close()


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
    config_path = ensure_runtime_config()
    return CastleSettings(_env_file=None, _json_file=str(config_path), **kwargs)


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
                contributor=getattr(args, "contributor", None),
                limit=args.results,
            )
        )
        _print_section("Seek")
        _print_kv("Query", args.query or "")
        if args.wing:
            _print_kv("Wing", args.wing)
        if args.room:
            _print_kv("Room", args.room)
        if getattr(args, "contributor", None):
            _print_kv("Contributor", args.contributor)
        if not result.results:
            print("  No results found.")
            return
        _print_kv("Results", len(result.results))
        for i, hit in enumerate(result.results, 1):
            label = f"\n  [{i}] {hit.wing} / {hit.room}"
            if getattr(hit, "contributor", None):
                label += f" by {hit.contributor}"
            label += f"  (match: {hit.similarity})"
            print(label)
            print(f"      {hit.text[:200]}")


def cmd_project(args):
    from swampcastle.mining.rooms import detect_rooms_local

    project_dir = os.path.expanduser(args.dir)
    if not os.path.isdir(project_dir):
        print(f"  Error: {project_dir} is not a directory")
        sys.exit(1)

    detect_rooms_local(
        project_dir,
        yes=args.yes,
        wing=getattr(args, "wing", None),
        team=getattr(args, "team", None),
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
            explain=getattr(args, "explain", False),
        )


def cmd_herald(args):
    """Print the stable SwampCastle protocol for agent wake-up."""
    from swampcastle.castle import Castle

    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        print(castle.catalog.status().protocol)


def cmd_brief(args):
    """Print a wing-scoped briefing for prompt/context injection."""
    from swampcastle.castle import Castle

    settings = _settings(args)
    with Castle(settings, factory_from_settings(settings)) as castle:
        brief = castle.catalog.brief(args.wing)

    _print_section("Brief")
    _print_kv("Wing", brief.wing)
    _print_kv("Drawers", brief.total_drawers)
    _print_kv("Files", brief.source_files)

    if brief.error:
        _print_kv("Warning", brief.error)

    if brief.total_drawers == 0:
        print("  No drawers found for that wing.")
        return

    rooms = ", ".join(
        f"{name} ({count})"
        for name, count in sorted(brief.rooms.items(), key=lambda item: (-item[1], item[0]))
    )
    _print_kv("Rooms", rooms)

    if brief.contributors:
        contributors = ", ".join(
            f"{name} ({count})"
            for name, count in sorted(
                brief.contributors.items(), key=lambda item: (-item[1], item[0])
            )
        )
        _print_kv("Contributors", contributors)


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
    apply = getattr(args, "apply", False)
    effective_dry_run = args.dry_run or not apply

    with Castle(settings, factory_from_settings(settings)) as castle:
        count = castle.vault.distill(
            wing=args.wing,
            room=args.room,
            dry_run=effective_dry_run,
            config_path=config_path,
        )
        if count == 0:
            print("  No drawers to distill.")
            return

        if effective_dry_run:
            print(f"  DRY RUN — would distill {count} drawers.")
            if not args.dry_run and not apply:
                print(
                    "  Preview mode is the default. Re-run with --apply to persist AAAK metadata."
                )
        else:
            print(f"  Distilled {count} drawers with AAAK dialect.")


def cmd_wizard(args):
    from swampcastle.wizard import run_wizard

    run_wizard()


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
    for model in models:
        print(
            "    "
            f"{model['name']} "
            f"(alias: {model['alias']}, dim: {model['dim']}, backend: {model['backend']})"
        )
        print(f"      {model['notes']}")


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


def _scan_deskeleton_targets(
    vault,
    where,
    target_store: DeskeletonTargetStore,
    *,
    batch_size: int = DESKELETON_BATCH_SIZE,
):
    """Scan drawers page-by-page and persist unique deskeleton targets on disk."""
    skeleton_count = 0
    unique_count = 0
    offset = 0

    while True:
        results = vault.get_drawers(
            where=where or None,
            include=["metadatas"],
            limit=batch_size,
            offset=offset,
        )
        metadatas = results.get("metadatas", [])
        if not metadatas:
            break

        for meta in metadatas:
            if not meta.get("is_skeleton"):
                continue
            source_file = meta.get("source_file")
            source_wing = meta.get("wing")
            if not source_file or not source_wing:
                continue

            skeleton_count += 1
            if target_store.add(source_wing, source_file):
                unique_count += 1

        if len(metadatas) < batch_size:
            break
        offset += batch_size

    return skeleton_count, unique_count


def cmd_deskeleton(args):
    """Identify and replace skeleton drawers with full implementations."""
    from swampcastle.castle import Castle
    from swampcastle.mining.miner import mine

    settings = _settings(args)
    factory = factory_from_settings(settings)
    with Castle(settings, factory) as castle:
        where = {}
        if args.wing:
            where["wing"] = args.wing
        if args.room:
            where["room"] = args.room

        with tempfile.TemporaryDirectory(prefix="swampcastle-deskeleton-") as temp_dir:
            target_store = DeskeletonTargetStore(Path(temp_dir) / "targets.sqlite3")
            try:
                skeleton_count, unique_count = _scan_deskeleton_targets(
                    castle.vault,
                    where or None,
                    target_store,
                )

                if skeleton_count == 0:
                    print("  No skeleton drawers found.")
                    return

                _print_section("Deskeleton")
                _print_kv("Skeletons found", skeleton_count)
                _print_kv("Source files", unique_count)

                for source_wing, source_file in target_store.iter_targets():
                    if args.dry_run:
                        print(f"  [DRY RUN] Would re-mine ({source_wing}): {source_file}")
                        continue

                    sf_path = Path(source_file)
                    if not sf_path.exists():
                        print(f"  Warning: source file missing, skipping: {source_file}")
                        continue

                    config_path = resolve_project_config(str(sf_path.parent))
                    if not config_path:
                        curr = sf_path.parent
                        while curr != curr.parent:
                            config_path = resolve_project_config(str(curr))
                            if config_path:
                                break
                            curr = curr.parent

                    if not config_path:
                        print(f"  Warning: No .swampcastle.yaml found for {source_file}, skipping.")
                        continue

                    project_dir = str(config_path.parent)
                    try:
                        rel = str(sf_path.relative_to(project_dir))
                    except ValueError:
                        print(
                            f"  Warning: {source_file} is not under project dir {project_dir}, skipping."
                        )
                        continue

                    print(f"  Deskeletonizing ({source_wing}): {source_file}")
                    mine(
                        project_dir=project_dir,
                        palace_path=str(settings.castle_path),
                        wing=source_wing,
                        agent="swampcastle-deskeleton",
                        storage_factory=factory,
                        force_no_skeleton=True,
                        _force_remine=True,
                        only_force_included=True,
                        include_ignored=[rel],
                        respect_gitignore=False,
                    )
            finally:
                target_store.close()
