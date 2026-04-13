#!/usr/bin/env python3
"""Legacy ChromaDB palace migration for SwampCastle v4.

This module migrates drawer data out of an on-disk ChromaDB palace and into
SwampCastle's v4 local castle layout (LanceDB + sidecar files).

The source palace is never modified. Migration reads the old SQLite store and
writes into a new target castle directory.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swampcastle.settings import CastleSettings
from swampcastle.storage import StorageFactory, factory_from_settings

COLLECTION_NAME = "swampcastle_chests"
BATCH_SIZE = 500
SIDECAR_FILES = ["knowledge_graph.sqlite3", "identity.txt", "node_id", "seq"]


@dataclass
class MigrationReport:
    source_palace: Path
    target_castle: Path
    drawers_found: int
    drawers_migrated: int
    dry_run: bool
    source_version: str
    sidecars_copied: list[str] = field(default_factory=list)


def resolve_source_palace(source_palace: str | None = None) -> Path:
    """Resolve the legacy ChromaDB palace directory.

    Search order:
    1. explicit source path
    2. ~/.mempalace/palace
    3. ~/.swampcastle/palace
    """
    candidates: list[Path] = []
    if source_palace:
        candidates.append(Path(source_palace).expanduser())
    else:
        home = Path.home()
        candidates.extend([
            home / ".mempalace" / "palace",
            home / ".swampcastle" / "palace",
        ])

    for palace_dir in candidates:
        db_path = palace_dir / "chroma.sqlite3"
        if db_path.is_file():
            return palace_dir

    if source_palace:
        raise FileNotFoundError(f"No ChromaDB palace found at {Path(source_palace).expanduser()}")
    raise FileNotFoundError(
        "No legacy ChromaDB palace found. Checked ~/.mempalace/palace and ~/.swampcastle/palace"
    )


def extract_drawers_from_sqlite(db_path: str) -> list[dict[str, Any]]:
    """Read all drawers directly from ChromaDB's SQLite store."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT e.embedding_id,
                   MAX(CASE WHEN em.key = 'chroma:document' THEN em.string_value END) AS document
            FROM embeddings e
            JOIN embedding_metadata em ON em.id = e.id
            GROUP BY e.embedding_id
            """
        ).fetchall()

        drawers = []
        for row in rows:
            document = row["document"]
            if not document:
                continue

            meta_rows = conn.execute(
                """
                SELECT em.key, em.string_value, em.int_value, em.float_value, em.bool_value
                FROM embedding_metadata em
                JOIN embeddings e ON e.id = em.id
                WHERE e.embedding_id = ?
                  AND em.key NOT LIKE 'chroma:%'
                """,
                (row["embedding_id"],),
            ).fetchall()

            metadata: dict[str, Any] = {}
            for meta_row in meta_rows:
                key = meta_row["key"]
                if meta_row["string_value"] is not None:
                    metadata[key] = meta_row["string_value"]
                elif meta_row["int_value"] is not None:
                    metadata[key] = meta_row["int_value"]
                elif meta_row["float_value"] is not None:
                    metadata[key] = meta_row["float_value"]
                elif meta_row["bool_value"] is not None:
                    metadata[key] = bool(meta_row["bool_value"])

            drawers.append(
                {
                    "id": row["embedding_id"],
                    "document": document,
                    "metadata": metadata,
                }
            )
        return drawers
    finally:
        conn.close()


def detect_chromadb_version(db_path: str) -> str:
    """Best-effort schema fingerprinting for old ChromaDB palaces."""
    conn = sqlite3.connect(db_path)
    try:
        try:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(collections)").fetchall()]
        except sqlite3.DatabaseError:
            return "unknown"
        if "schema_str" in columns:
            return "1.x"
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        if "embeddings_queue" in tables:
            return "0.6.x"
        if "embedding_metadata" in tables and "embeddings" in tables:
            return "legacy"
        return "unknown"
    finally:
        conn.close()


def _summarize_drawers(drawers: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for drawer in drawers:
        metadata = drawer["metadata"]
        wing = metadata.get("wing", "unknown")
        room = metadata.get("room", "unknown")
        summary[wing][room] += 1
    return summary


def _default_target_factory(target_castle: Path) -> StorageFactory:
    settings = CastleSettings(
        _env_file=None,
        castle_path=target_castle,
        backend="lance",
    )
    return factory_from_settings(settings)


def _copy_sidecars(source_root: Path, target_root: Path) -> list[str]:
    copied: list[str] = []

    for filename in SIDECAR_FILES:
        source = source_root / filename
        target = target_root / filename
        if not source.exists() or target.exists():
            continue
        shutil.copy2(source, target)
        copied.append(filename)

    source_wal = source_root / "wal"
    target_wal = target_root / "wal"
    if source_wal.is_dir() and not target_wal.exists():
        shutil.copytree(source_wal, target_wal)
        copied.append("wal/")

    return copied


def _print_summary(report: MigrationReport, drawers: list[dict[str, Any]]) -> None:
    summary = _summarize_drawers(drawers)

    print(f"\n{'=' * 60}")
    print("  SwampCastle Raise")
    print(f"{'=' * 60}")
    print(f"  Source palace: {report.source_palace}")
    print(f"  Source DB:     {report.source_palace / 'chroma.sqlite3'}")
    print(f"  Source ver:    ChromaDB {report.source_version}")
    print(f"  Target castle: {report.target_castle}")
    print(f"  Drawers:       {report.drawers_found}")
    print(f"  Mode:          {'DRY RUN' if report.dry_run else 'LIVE'}")

    if summary:
        print("\n  By wing / room:")
        for wing, rooms in sorted(summary.items()):
            total = sum(rooms.values())
            print(f"    WING: {wing} ({total})")
            for room, count in sorted(rooms.items(), key=lambda item: item[1], reverse=True):
                print(f"      ROOM: {room:24} {count:5}")

    if report.dry_run:
        print("\n  DRY RUN — no changes written.")
    else:
        print(f"\n  Migrated:      {report.drawers_migrated}")
        if report.sidecars_copied:
            print(f"  Sidecars:      {', '.join(report.sidecars_copied)}")
        else:
            print("  Sidecars:      none copied")
    print(f"{'=' * 60}\n")


def migrate(
    source_palace: str | None = None,
    target_castle: str | None = None,
    dry_run: bool = False,
    target_factory: StorageFactory | None = None,
) -> MigrationReport:
    """Migrate a legacy ChromaDB palace into a v4 local castle."""
    source_path = resolve_source_palace(source_palace)
    source_db = source_path / "chroma.sqlite3"
    source_root = source_path.parent

    if target_castle is None:
        target_path = CastleSettings(_env_file=None).castle_path
    else:
        target_path = Path(target_castle).expanduser()

    if source_path.resolve() == target_path.resolve():
        raise ValueError("Source palace and target castle must be different paths")

    if target_path.exists():
        if not target_path.is_dir() or any(target_path.iterdir()):
            raise FileExistsError(f"Target castle already exists and is not empty: {target_path}")

    drawers = extract_drawers_from_sqlite(str(source_db))
    if not drawers:
        raise ValueError(
            f"No drawers found in source palace at {source_path}. "
            "The database may be empty or corrupted."
        )

    report = MigrationReport(
        source_palace=source_path,
        target_castle=target_path,
        drawers_found=len(drawers),
        drawers_migrated=0,
        dry_run=dry_run,
        source_version=detect_chromadb_version(str(source_db)),
    )

    if dry_run:
        _print_summary(report, drawers)
        return report

    # NOTE: Migration is NOT atomic. If upsert fails partway, some drawers may
    # be written while others are not. The source palace is never modified.
    target_root = target_path.parent
    target_root.mkdir(parents=True, exist_ok=True)
    target_path.mkdir(parents=True, exist_ok=True)

    created_targets: list[Path] = [target_path]
    own_factory = target_factory is None
    factory = target_factory or _default_target_factory(target_path)

    try:
        # Copy sidecars FIRST so they're tracked for cleanup on error
        report.sidecars_copied = _copy_sidecars(source_root, target_root)
        for name in report.sidecars_copied:
            if name == "wal/":
                created_targets.append(target_root / "wal")
            else:
                created_targets.append(target_root / name)

        # Now perform the upsert operations
        collection = factory.open_collection(COLLECTION_NAME)
        for start in range(0, len(drawers), BATCH_SIZE):
            batch = drawers[start : start + BATCH_SIZE]
            collection.upsert(
                ids=[drawer["id"] for drawer in batch],
                documents=[drawer["document"] for drawer in batch],
                metadatas=[drawer["metadata"] for drawer in batch],
            )
            report.drawers_migrated += len(batch)
    except Exception:
        if own_factory:
            factory.close()
        # Clean up all created resources in reverse order
        for created in reversed(created_targets):
            if created.is_dir():
                shutil.rmtree(created, ignore_errors=True)
            elif created.exists():
                created.unlink(missing_ok=True)
        raise
    else:
        if own_factory:
            factory.close()

    _print_summary(report, drawers)
    return report
