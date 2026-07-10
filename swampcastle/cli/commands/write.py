"""CLI write / ingest command handlers: project, gather, cleave, distill, reforge, deskeleton."""

import logging
import os
import sys
import tempfile
from pathlib import Path

from swampcastle.cli.commands.shared import (
    DESKELETON_BATCH_SIZE,
    DeskeletonTargetStore,
    _print_kv,
    _print_progress,
    _print_section,
    _settings,
)
from swampcastle.project_config import resolve_project_config

logger = logging.getLogger("swampcastle.cli.commands")


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

    # Best-effort wayfinder-map autodetection — never breaks project setup.
    try:
        from swampcastle.mining import tracker

        detected = tracker.detect_tracker_repo(project_dir)
        if detected is not None:
            forge, repo = detected
            if tracker.probe_wayfinder_map(forge, repo) and tracker.register_tracker_repo(
                forge, repo
            ):
                print(f"  Wayfinder map found on {forge}:{repo} — registered for tracker sweep.")
    except Exception as exc:
        logger.debug("Tracker autodetection skipped: %s", exc)


def cmd_gather(args):
    settings = _settings(args)
    palace_path = str(settings.castle_path)
    project_dir = os.path.expanduser(args.dir)
    storage_factory = None
    progress_callback = None
    phase_progress_callback = None
    if not args.dry_run:
        from swampcastle.storage import factory_from_settings

        storage_factory = factory_from_settings(settings)
        if args.mode == "projects" and not getattr(args, "explain", False):

            def phase_progress_callback(phase: str, processed: int, total: int) -> None:
                labels = {
                    "mine": "Mining",
                    "flush": "Flushing",
                    "kg_extract": "Extracting KG",
                }
                _print_progress(labels.get(phase, phase.title()), processed, total)

    _print_section("Gather")
    _print_kv("Mode", args.mode)
    _print_kv("Source", project_dir)
    _print_kv("Castle", palace_path)
    if args.wing:
        _print_kv("Wing", args.wing)

    try:
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
                extract_kg_proposals=getattr(args, "extract_kg_proposals", False),
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
                extract_kg_proposals=getattr(args, "extract_kg_proposals", False),
                embed_batch_size=getattr(settings, "embed_batch_size", None),
                progress_callback=progress_callback,
                phase_progress_callback=phase_progress_callback,
            )
    except KeyboardInterrupt:
        print("\n  Cancelled by user.")
        raise SystemExit(130)
    finally:
        if storage_factory is not None:
            try:
                storage_factory.close()
            except Exception as exc:
                logger.warning("Error closing storage factory after gather: %s", exc)


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
    progress_callback = None
    phase_progress_callback = None

    if not effective_dry_run:

        def phase_progress_callback(phase: str, processed: int, total: int) -> None:
            labels = {"distill": "Distilling", "persist": "Persisting"}
            _print_progress(labels.get(phase, phase.title()), processed, total)

    with Castle(settings, factory_from_settings(settings)) as castle:
        count = castle.vault.distill(
            wing=args.wing,
            room=args.room,
            dry_run=effective_dry_run,
            config_path=config_path,
            progress_callback=progress_callback,
            phase_progress_callback=phase_progress_callback,
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

    progress_callback = None
    if not args.dry_run:

        def progress_callback(processed: int, total: int) -> None:
            _print_progress("Reforging", processed, total)

    with Castle(settings, factory_from_settings(settings), skip_embedder_check=True) as castle:
        count = castle.vault.reforge(
            wing=args.wing,
            room=args.room,
            dry_run=args.dry_run,
            progress_callback=progress_callback,
        )
        if count == 0:
            print("  No drawers to reforge.")
            return

        if args.dry_run:
            print(f"  DRY RUN — would reforge {count} drawers.")
        else:
            embedder_info = embedder or settings.embedder
            print(f"  Reforged {count} drawers with {embedder_info} embedder.")


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
    from swampcastle.storage import factory_from_settings

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


def cmd_sweep(args):
    # Line-buffer stdout so per-file progress reaches the systemd journal live.
    # (PYTHONUNBUFFERED alone can't do it: pipx console scripts run python -E.)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass

    settings = _settings(args)
    palace_path = str(settings.castle_path)

    if getattr(args, "install_timer", False):
        from swampcastle.mining.sweep import install_timer

        written = install_timer()
        _print_section("Sweep timer")
        for path in written:
            _print_kv("Wrote", str(path))
        print("  Enabled: swampcastle-sweep.timer (every 6h, persistent)")
        return

    storage_factory = None
    if not args.dry_run:
        from swampcastle.storage import factory_from_settings

        storage_factory = factory_from_settings(settings)

    from swampcastle.mining.sweep import sweep_transcripts

    _print_section("Sweep")
    _print_kv("Castle", palace_path)
    if args.dry_run:
        _print_kv("Mode", "dry run")

    summary = sweep_transcripts(palace_path, storage_factory=storage_factory, dry_run=args.dry_run)

    _print_kv("Projects swept", str(summary["projects_swept"]))
    if summary["roots_missing"]:
        _print_kv("Roots missing", ", ".join(summary["roots_missing"]))
    if summary["oversize"]:
        print(
            f"  WARNING: {len(summary['oversize'])} oversize transcripts skipped (staleness gap):"
        )
        for path in summary["oversize"]:
            print(f"    - {path}")

    tracker_failed = False
    if not args.dry_run:
        from swampcastle.mining.tracker import sweep_trackers

        collection = storage_factory.open_collection("swampcastle_chests")
        tracker_summary = sweep_trackers(collection=collection)
        _print_kv(
            "Trackers swept",
            f"{tracker_summary['swept']} (+{tracker_summary['drawers']} drawers)",
        )
        if tracker_summary["stale"]:
            print(
                f"  WARNING: stale tracker entries skipped: {', '.join(tracker_summary['stale'])}"
            )
        if tracker_summary["auth_failed"]:
            print("  ERROR: forge auth failed — tracker ingest paused; refresh tea/gh credentials.")
        if tracker_summary["failed"]:
            print(f"  ERROR: {len(tracker_summary['failed'])} tracker repos failed:")
            for failure in tracker_summary["failed"]:
                print(f"    - {failure}")
        tracker_failed = bool(tracker_summary["failed"]) or tracker_summary["auth_failed"]

    if summary["projects_failed"]:
        print(f"  ERROR: {len(summary['projects_failed'])} project directories failed:")
        for failure in summary["projects_failed"]:
            print(f"    - {failure}")
    if summary["projects_failed"] or tracker_failed:
        sys.exit(1)


def cmd_install_hooks(args):
    from swampcastle.hooks_install import install_all

    result = install_all()
    _print_section("Install hooks")
    _print_kv("Launcher", str(result["wrapper"]))
    _print_kv(
        "Claude Code",
        "hooks added to ~/.claude/settings.json"
        if result["claude_settings_changed"]
        else "already installed",
    )
    _print_kv("pi", str(result["pi_extension"]))
    print("  Restart running sessions (or /reload in pi) to activate.")


def cmd_tracker(args):
    from swampcastle.mining import tracker

    action = getattr(args, "tracker_action", None)

    if action == "list":
        entries = tracker.list_tracker_repos()
        _print_section("Tracker repos")
        if not entries:
            print("  (none registered)")
        for e in entries:
            print(
                f"  {e.get('forge')}:{e.get('repo')} [{e.get('state')}] "
                f"label={e.get('label')} last_ok={e.get('last_ok') or 'never'} "
                f"failures={e.get('consecutive_failures', 0)}"
            )
        return

    if action == "remove":
        removed = tracker.remove_tracker_repo(args.repo)
        print(f"  {'Removed' if removed else 'Not registered:'} {args.repo}")
        return

    if action == "register":
        detected = tracker.detect_tracker_repo(os.path.expanduser(args.dir))
        if detected is None:
            print("  No known forge remote found in that directory.")
            sys.exit(1)
        forge, repo = detected
        try:
            has_map = tracker.probe_wayfinder_map(forge, repo)
        except tracker.TrackerError as exc:
            print(f"  Probe of {forge}:{repo} failed: {exc}")
            sys.exit(1)
        if not has_map:
            print(f"  No {tracker.DEFAULT_LABEL} issues on {forge}:{repo} — not registering.")
            return
        added = tracker.register_tracker_repo(forge, repo)
        print(
            f"  {'Registered' if added else 'Already registered:'} {forge}:{repo} "
            f"(label {tracker.DEFAULT_LABEL})"
        )
        return

    if action == "ingest":
        forge = args.forge
        if forge is None:
            entry = next(
                (e for e in tracker.list_tracker_repos() if e.get("repo") == args.repo),
                None,
            )
            forge = entry["forge"] if entry else "gitea"

        collection = None
        if not args.dry_run:
            from swampcastle.storage import factory_from_settings

            settings = _settings(args)
            collection = factory_from_settings(settings).open_collection("swampcastle_chests")

        _print_section("Tracker ingest")
        _print_kv("Repo", f"{forge}:{args.repo}")
        result = tracker.ingest_tracker_repo(
            forge, args.repo, collection=collection, label=args.label, dry_run=args.dry_run
        )
        _print_kv("Drawers filed", str(result["drawers"]))
        _print_kv("Unchanged", str(result["skipped"]))
