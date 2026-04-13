"""Tests for swampcastle.migrate — ChromaDB to v4 castle migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from swampcastle.migrate import extract_drawers_from_sqlite, migrate, resolve_source_palace
from swampcastle.storage.memory import InMemoryStorageFactory


def _write_chroma_sqlite(palace_dir: Path, records: list[dict]) -> Path:
    palace_dir.mkdir(parents=True, exist_ok=True)
    db_path = palace_dir / "chroma.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE collections (
                id TEXT PRIMARY KEY,
                name TEXT,
                schema_str TEXT
            );
            CREATE TABLE embeddings (
                id INTEGER PRIMARY KEY,
                embedding_id TEXT NOT NULL
            );
            CREATE TABLE embedding_metadata (
                id INTEGER NOT NULL,
                key TEXT NOT NULL,
                string_value TEXT,
                int_value INTEGER,
                float_value REAL,
                bool_value INTEGER
            );
            """
        )
        conn.execute(
            "INSERT INTO collections (id, name, schema_str) VALUES (?, ?, ?)",
            ("c1", "swampcastle_chests", "{}"),
        )
        for index, record in enumerate(records, start=1):
            conn.execute(
                "INSERT INTO embeddings (id, embedding_id) VALUES (?, ?)",
                (index, record["id"]),
            )
            conn.execute(
                "INSERT INTO embedding_metadata (id, key, string_value) VALUES (?, ?, ?)",
                (index, "chroma:document", record["document"]),
            )
            for key, value in record["metadata"].items():
                if isinstance(value, bool):
                    conn.execute(
                        "INSERT INTO embedding_metadata (id, key, bool_value) VALUES (?, ?, ?)",
                        (index, key, int(value)),
                    )
                elif isinstance(value, int):
                    conn.execute(
                        "INSERT INTO embedding_metadata (id, key, int_value) VALUES (?, ?, ?)",
                        (index, key, value),
                    )
                elif isinstance(value, float):
                    conn.execute(
                        "INSERT INTO embedding_metadata (id, key, float_value) VALUES (?, ?, ?)",
                        (index, key, value),
                    )
                else:
                    conn.execute(
                        "INSERT INTO embedding_metadata (id, key, string_value) VALUES (?, ?, ?)",
                        (index, key, str(value)),
                    )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_extract_drawers_from_sqlite_reads_documents_and_metadata(tmp_path):
    db_path = _write_chroma_sqlite(
        tmp_path / "palace",
        [
            {
                "id": "drawer-1",
                "document": "auth migration notes",
                "metadata": {
                    "wing": "proj",
                    "room": "auth",
                    "source_file": "notes.md",
                    "chunk_index": 1,
                    "is_reviewed": True,
                },
            }
        ],
    )

    drawers = extract_drawers_from_sqlite(str(db_path))

    assert drawers == [
        {
            "id": "drawer-1",
            "document": "auth migration notes",
            "metadata": {
                "wing": "proj",
                "room": "auth",
                "source_file": "notes.md",
                "chunk_index": 1,
                "is_reviewed": True,
            },
        }
    ]


def test_resolve_source_palace_prefers_explicit_path(tmp_path):
    source = tmp_path / "legacy" / "palace"
    _write_chroma_sqlite(source, [])

    assert resolve_source_palace(str(source)) == source


def test_resolve_source_palace_detects_common_legacy_locations(tmp_path, monkeypatch):
    mempalace = tmp_path / ".mempalace" / "palace"
    _write_chroma_sqlite(mempalace, [])
    monkeypatch.setattr("swampcastle.migrate.Path.home", lambda: tmp_path)

    assert resolve_source_palace() == mempalace


def test_migrate_dry_run_reports_without_writing(tmp_path):
    source_palace = tmp_path / "legacy" / "palace"
    _write_chroma_sqlite(
        source_palace,
        [
            {
                "id": "drawer-1",
                "document": "auth migration notes",
                "metadata": {"wing": "proj", "room": "auth", "source_file": "notes.md"},
            },
            {
                "id": "drawer-2",
                "document": "billing retry notes",
                "metadata": {"wing": "proj", "room": "billing", "source_file": "billing.md"},
            },
        ],
    )

    target_factory = InMemoryStorageFactory()
    report = migrate(
        source_palace=str(source_palace),
        target_castle=str(tmp_path / "castle"),
        dry_run=True,
        target_factory=target_factory,
    )

    assert report.drawers_found == 2
    assert report.drawers_migrated == 0
    assert target_factory.open_collection("swampcastle_chests").count() == 0


def test_migrate_imports_into_target_factory_and_copies_sidecars(tmp_path):
    source_root = tmp_path / "legacy"
    source_palace = source_root / "palace"
    _write_chroma_sqlite(
        source_palace,
        [
            {
                "id": "drawer-1",
                "document": "auth migration notes",
                "metadata": {"wing": "proj", "room": "auth", "source_file": "notes.md"},
            },
            {
                "id": "drawer-2",
                "document": "billing retry notes",
                "metadata": {"wing": "proj", "room": "billing", "source_file": "billing.md"},
            },
        ],
    )
    (source_root / "knowledge_graph.sqlite3").write_text("kg")
    (source_root / "identity.txt").write_text("I am old swamp memory")
    (source_root / "node_id").write_text("abc123")
    (source_root / "seq").write_text("42")
    wal_dir = source_root / "wal"
    wal_dir.mkdir()
    (wal_dir / "write_log.jsonl").write_text("{}\n")

    target_castle = tmp_path / "swampcastle" / "castle"
    target_factory = InMemoryStorageFactory()
    report = migrate(
        source_palace=str(source_palace),
        target_castle=str(target_castle),
        dry_run=False,
        target_factory=target_factory,
    )

    collection = target_factory.open_collection("swampcastle_chests")
    assert collection.count() == 2
    result = collection.get(ids=["drawer-1"], include=["documents", "metadatas"])
    assert result["documents"] == ["auth migration notes"]
    assert result["metadatas"][0]["room"] == "auth"

    assert report.drawers_found == 2
    assert report.drawers_migrated == 2
    assert report.sidecars_copied == [
        "knowledge_graph.sqlite3",
        "identity.txt",
        "node_id",
        "seq",
        "wal/",
    ]
    assert (target_castle.parent / "knowledge_graph.sqlite3").read_text() == "kg"
    assert (target_castle.parent / "identity.txt").read_text() == "I am old swamp memory"
    assert (target_castle.parent / "node_id").read_text() == "abc123"
    assert (target_castle.parent / "seq").read_text() == "42"
    assert (target_castle.parent / "wal" / "write_log.jsonl").read_text() == "{}\n"


def test_migrate_refuses_existing_nonempty_target(tmp_path):
    source_palace = tmp_path / "legacy" / "palace"
    _write_chroma_sqlite(source_palace, [{"id": "d1", "document": "x", "metadata": {}}])

    target_castle = tmp_path / "swampcastle" / "castle"
    target_castle.mkdir(parents=True)
    (target_castle / "existing.txt").write_text("already here")

    with pytest.raises(FileExistsError, match="already exists"):
        migrate(
            source_palace=str(source_palace),
            target_castle=str(target_castle),
            dry_run=False,
            target_factory=InMemoryStorageFactory(),
        )


def test_migrate_raises_for_empty_source(tmp_path):
    source_palace = tmp_path / "legacy" / "palace"
    _write_chroma_sqlite(source_palace, [])  # empty

    with pytest.raises(ValueError, match="No drawers found"):
        migrate(
            source_palace=str(source_palace),
            target_castle=str(tmp_path / "castle"),
            dry_run=False,
            target_factory=InMemoryStorageFactory(),
        )


def test_migrate_cleans_up_sidecars_on_upsert_failure(tmp_path):
    """If upsert fails, sidecars should be cleaned up along with castle dir."""
    source_root = tmp_path / "legacy"
    source_palace = source_root / "palace"
    _write_chroma_sqlite(
        source_palace,
        [{"id": "d1", "document": "content", "metadata": {"wing": "test"}}],
    )
    (source_root / "identity.txt").write_text("identity")
    (source_root / "node_id").write_text("node123")

    target_castle = tmp_path / "swampcastle" / "castle"
    target_root = target_castle.parent

    class FailingFactory:
        def open_collection(self, name):
            return FailingCollection()
        def close(self):
            pass

    class FailingCollection:
        def upsert(self, **kwargs):
            raise RuntimeError("Simulated upsert failure")

    with pytest.raises(RuntimeError, match="Simulated upsert failure"):
        migrate(
            source_palace=str(source_palace),
            target_castle=str(target_castle),
            dry_run=False,
            target_factory=FailingFactory(),
        )

    # Verify cleanup: castle dir and sidecars should NOT exist
    assert not target_castle.exists(), "Castle dir should be cleaned up"
    assert not (target_root / "identity.txt").exists(), "Sidecar should be cleaned up"
    assert not (target_root / "node_id").exists(), "Sidecar should be cleaned up"
