"""CLI ops / admin command handlers."""

import json
import os
import sys

from swampcastle.cli.commands.shared import (
    _print_kv,
    _print_progress,
    _print_section,
    _settings,
)
from swampcastle.storage import factory_from_settings


def cmd_raise(args):
    from swampcastle.migrate import migrate

    target_castle = getattr(args, "target_castle", None) or getattr(args, "palace", None)
    migrate(
        source_palace=getattr(args, "source_palace", None),
        target_castle=target_castle,
        dry_run=getattr(args, "dry_run", False),
    )


def cmd_armory(args):
    from swampcastle.embeddings import (
        build_embedding_verification_report,
        get_embedder,
        list_embedders,
    )

    if getattr(args, "verify", False):
        import json

        settings = _settings(args)
        embedder = get_embedder(settings.embedder_config)
        report = build_embedding_verification_report(embedder)
        if getattr(args, "json", False):
            print(json.dumps(report, indent=2, sort_keys=True))
            return

        _print_section("Embedder verification")
        _print_kv("Backend", report["embedder"].get("backend", "unknown"))
        _print_kv("Model", report["embedder"].get("model_name", "unknown"))
        _print_kv("Dimension", report["embedder"].get("dimension", "unknown"))
        _print_kv("Fingerprint", report["fingerprint_hash"])
        _print_kv("Probe hash", report["probe_hash"])
        _print_kv("Probe texts", report["probe_count"])
        return

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
        result = client.sync(
            engine,
            pull_progress=lambda received, total: _print_progress("Pulling", received, total),
        )
        _print_kv("Pushed", result.get("push", {}).get("sent", 0))
        _print_kv("Pulled", result.get("pull", {}).get("received", 0))


def cmd_ni(args):
    print("\n  We are the Knights who say... Ni!")
    print("  Bring us a shrubbery! (Or run: swampcastle build <dir>)\n")
