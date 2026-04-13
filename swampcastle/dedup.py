"""Deduplicate near-identical drawers within the same source file.

This utility is backend-agnostic: it works against any CollectionStore.
It uses the active storage backend configured in CastleSettings unless a
storage factory is injected explicitly.
"""

from __future__ import annotations

import argparse
import os
import time
from collections import defaultdict

from swampcastle.settings import CastleSettings
from swampcastle.storage import StorageFactory, factory_from_settings


COLLECTION_NAME = "swampcastle_chests"
DEFAULT_THRESHOLD = 0.15
MIN_DRAWERS_TO_CHECK = 5


def _get_castle_path():
    """Resolve the active castle path from settings."""
    return CastleSettings(_env_file=None).castle_path


def _open_collection(
    palace_path: str | None = None,
    *,
    storage_factory: StorageFactory | None = None,
):
    """Open the active collection via the configured storage factory."""
    if storage_factory is not None:
        castle_path = os.path.expanduser(palace_path) if palace_path else str(_get_castle_path())
        return castle_path, storage_factory.open_collection(COLLECTION_NAME)

    kwargs = {}
    if palace_path:
        kwargs["castle_path"] = os.path.expanduser(palace_path)
    settings = CastleSettings(_env_file=None, **kwargs)
    factory = factory_from_settings(settings)
    return str(settings.castle_path), factory.open_collection(settings.collection_name)


def get_source_groups(col, min_count=MIN_DRAWERS_TO_CHECK, source_pattern=None, wing=None):
    """Group drawer IDs by source_file for candidate dedup passes."""
    total = col.count()
    groups = defaultdict(list)

    offset = 0
    batch_size = 1000
    while offset < total:
        kwargs = {"limit": batch_size, "offset": offset, "include": ["metadatas"]}
        if wing:
            kwargs["where"] = {"wing": wing}
        batch = col.get(**kwargs)
        if not batch["ids"]:
            break
        for drawer_id, meta in zip(batch["ids"], batch["metadatas"]):
            source_file = meta.get("source_file", "unknown")
            if source_pattern and source_pattern.lower() not in source_file.lower():
                continue
            groups[source_file].append(drawer_id)
        offset += len(batch["ids"])

    return {source_file: ids for source_file, ids in groups.items() if len(ids) >= min_count}


def dedup_source_group(col, drawer_ids, threshold=DEFAULT_THRESHOLD, dry_run=True):
    """Greedily keep the richest documents and delete near-duplicates."""
    data = col.get(ids=drawer_ids, include=["documents", "metadatas"])
    items = list(zip(data["ids"], data["documents"], data["metadatas"]))
    items.sort(key=lambda item: len(item[1] or ""), reverse=True)

    kept: list[tuple[str, str]] = []
    to_delete: list[str] = []

    for drawer_id, document, metadata in items:
        if not document or len(document) < 20:
            to_delete.append(drawer_id)
            continue

        if not kept:
            kept.append((drawer_id, document))
            continue

        source_file = metadata.get("source_file", "")
        where = {"source_file": source_file} if source_file else None

        try:
            results = col.query(
                query_texts=[document],
                n_results=min(len(kept), 5),
                where=where,
                include=["distances"],
            )
            distances = results["distances"][0] if results["distances"] else []
            kept_ids = {item[0] for item in kept}

            duplicate_found = False
            for result_id, distance in zip(results["ids"][0], distances):
                if result_id in kept_ids and distance < threshold:
                    duplicate_found = True
                    break

            if duplicate_found:
                to_delete.append(drawer_id)
            else:
                kept.append((drawer_id, document))
        except Exception:
            kept.append((drawer_id, document))

    if to_delete and not dry_run:
        for start in range(0, len(to_delete), 500):
            col.delete(ids=to_delete[start : start + 500])

    return [item[0] for item in kept], to_delete


def show_stats(palace_path=None, *, storage_factory: StorageFactory | None = None):
    """Print duplicate-candidate stats without modifying data."""
    _, col = _open_collection(palace_path, storage_factory=storage_factory)
    groups = get_source_groups(col)

    total_drawers = sum(len(ids) for ids in groups.values())
    print(f"\n  Sources with {MIN_DRAWERS_TO_CHECK}+ drawers: {len(groups)}")
    print(f"  Total drawers in those sources: {total_drawers:,}")

    print("\n  Top 15 by drawer count:")
    sorted_groups = sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)
    for source_file, ids in sorted_groups[:15]:
        print(f"    {len(ids):4d}  {source_file[:65]}")

    estimated_dups = sum(int(len(ids) * 0.4) for ids in groups.values() if len(ids) > 20)
    print(f"\n  Estimated duplicates (groups > 20): ~{estimated_dups:,}")


def dedup_palace(
    palace_path=None,
    threshold=DEFAULT_THRESHOLD,
    dry_run=True,
    source_pattern=None,
    min_count=MIN_DRAWERS_TO_CHECK,
    wing=None,
    *,
    storage_factory: StorageFactory | None = None,
):
    """Deduplicate drawers in the active castle."""
    castle_path, col = _open_collection(palace_path, storage_factory=storage_factory)

    print(f"\n{'=' * 55}")
    print("  SwampCastle Deduplicator")
    print(f"{'=' * 55}")
    print(f"  Castle: {castle_path}")
    print(f"  Drawers: {col.count():,}")
    print(f"  Threshold: {threshold}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    if wing:
        print(f"  Wing: {wing}")
    print(f"{'─' * 55}")

    groups = get_source_groups(col, min_count, source_pattern, wing=wing)
    print(f"\n  Sources to check: {len(groups)}")

    started_at = time.time()
    total_kept = 0
    total_deleted = 0

    sorted_groups = sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)
    for index, (source_file, drawer_ids) in enumerate(sorted_groups, start=1):
        kept, deleted = dedup_source_group(col, drawer_ids, threshold, dry_run)
        total_kept += len(kept)
        total_deleted += len(deleted)

        if deleted:
            print(
                f"  [{index:3d}/{len(groups)}] "
                f"{source_file[:50]:50s} {len(drawer_ids):4d} → {len(kept):4d}  "
                f"(-{len(deleted)})"
            )

    elapsed = time.time() - started_at
    print(f"\n{'─' * 55}")
    print(f"  Done in {elapsed:.1f}s")
    print(
        f"  Drawers: {total_kept + total_deleted:,} → {total_kept:,}  (-{total_deleted:,} removed)"
    )
    print(f"  Castle after: {col.count():,} drawers")
    if dry_run:
        print("\n  [DRY RUN] No changes written. Re-run without --dry-run to apply.")
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deduplicate near-identical drawers")
    parser.add_argument("--palace", default=None, help="Castle directory path")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Cosine distance threshold (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    parser.add_argument("--wing", default=None, help="Scope dedup to a single wing")
    parser.add_argument("--source", default=None, help="Filter by source file pattern")
    args = parser.parse_args()

    path = os.path.expanduser(args.palace) if args.palace else None
    if args.stats:
        show_stats(palace_path=path)
    else:
        dedup_palace(
            palace_path=path,
            threshold=args.threshold,
            dry_run=args.dry_run,
            source_pattern=args.source,
            wing=args.wing,
        )
