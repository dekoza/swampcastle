"""Tests for swampcastle.dedup — near-duplicate drawer detection and removal."""

from unittest.mock import MagicMock

from swampcastle import dedup
from swampcastle.storage.memory import InMemoryStorageFactory


def _seed_factory(factory: InMemoryStorageFactory, *, wing: str = "proj"):
    col = factory.open_collection(dedup.COLLECTION_NAME)
    col.upsert(
        ids=["d1", "d2", "d3", "d4", "d5"],
        documents=[
            "auth token rotation policy for api gateway and session refresh",
            "auth token rotation policy for api gateway and session refresh",
            "auth token rotation policy for api gateway and session refresh",
            "billing retry strategy for failed invoices and payment recovery",
            "deployment notes for blue green rollouts and rollback strategy",
        ],
        metadatas=[
            {"wing": wing, "room": "auth", "source_file": "src/auth.py"},
            {"wing": wing, "room": "auth", "source_file": "src/auth.py"},
            {"wing": wing, "room": "auth", "source_file": "src/auth.py"},
            {"wing": wing, "room": "billing", "source_file": "src/auth.py"},
            {"wing": wing, "room": "deploy", "source_file": "src/auth.py"},
        ],
    )
    return col


# ── get_source_groups ─────────────────────────────────────────────────


def test_get_source_groups_basic():
    col = MagicMock()
    col.count.return_value = 5
    col.get.side_effect = [
        {
            "ids": ["d1", "d2", "d3", "d4", "d5"],
            "metadatas": [
                {"source_file": "a.txt"},
                {"source_file": "a.txt"},
                {"source_file": "a.txt"},
                {"source_file": "a.txt"},
                {"source_file": "a.txt"},
            ],
        },
        {"ids": []},
    ]
    groups = dedup.get_source_groups(col, min_count=5)
    assert "a.txt" in groups
    assert len(groups["a.txt"]) == 5


def test_get_source_groups_below_min():
    col = MagicMock()
    col.count.return_value = 2
    col.get.side_effect = [
        {
            "ids": ["d1", "d2"],
            "metadatas": [
                {"source_file": "a.txt"},
                {"source_file": "a.txt"},
            ],
        },
        {"ids": []},
    ]
    groups = dedup.get_source_groups(col, min_count=5)
    assert len(groups) == 0


def test_get_source_groups_source_filter():
    col = MagicMock()
    col.count.return_value = 6
    col.get.side_effect = [
        {
            "ids": ["d1", "d2", "d3", "d4", "d5", "d6"],
            "metadatas": [
                {"source_file": "project_a.txt"},
                {"source_file": "project_a.txt"},
                {"source_file": "project_a.txt"},
                {"source_file": "project_a.txt"},
                {"source_file": "project_a.txt"},
                {"source_file": "other.txt"},
            ],
        },
        {"ids": []},
    ]
    groups = dedup.get_source_groups(col, min_count=5, source_pattern="project_a")
    assert "project_a.txt" in groups
    assert "other.txt" not in groups


def test_get_source_groups_wing_filter():
    col = MagicMock()
    col.count.return_value = 5
    col.get.side_effect = [
        {
            "ids": ["d1", "d2", "d3", "d4", "d5"],
            "metadatas": [
                {"source_file": "a.txt"},
                {"source_file": "a.txt"},
                {"source_file": "a.txt"},
                {"source_file": "a.txt"},
                {"source_file": "a.txt"},
            ],
        },
        {"ids": []},
    ]
    dedup.get_source_groups(col, min_count=5, wing="my_wing")
    first_call = col.get.call_args_list[0]
    assert first_call.kwargs.get("where") == {"wing": "my_wing"}


def test_get_source_groups_missing_source_file():
    col = MagicMock()
    col.count.return_value = 5
    col.get.side_effect = [
        {
            "ids": ["d1", "d2", "d3", "d4", "d5"],
            "metadatas": [{}, {}, {}, {}, {}],
        },
        {"ids": []},
    ]
    groups = dedup.get_source_groups(col, min_count=5)
    assert "unknown" in groups


# ── dedup_source_group ────────────────────────────────────────────────


def test_dedup_source_group_all_unique():
    col = MagicMock()
    col.get.return_value = {
        "ids": ["d1", "d2"],
        "documents": ["long document one content here", "different document two here"],
        "metadatas": [
            {"wing": "a", "source_file": "a.txt"},
            {"wing": "a", "source_file": "a.txt"},
        ],
    }
    col.query.return_value = {
        "ids": [["d1"]],
        "distances": [[0.8]],
    }
    kept, deleted = dedup.dedup_source_group(col, ["d1", "d2"], threshold=0.15, dry_run=True)
    assert len(kept) == 2
    assert len(deleted) == 0
    assert col.query.call_args.kwargs["where"] == {"source_file": "a.txt"}


def test_dedup_source_group_with_duplicate():
    col = MagicMock()
    col.get.return_value = {
        "ids": ["d1", "d2"],
        "documents": [
            "long document content that is fairly long",
            "long document content that is fairly long",
        ],
        "metadatas": [
            {"wing": "a", "source_file": "a.txt"},
            {"wing": "a", "source_file": "a.txt"},
        ],
    }
    col.query.return_value = {
        "ids": [["d1"]],
        "distances": [[0.05]],
    }
    kept, deleted = dedup.dedup_source_group(col, ["d1", "d2"], threshold=0.15, dry_run=True)
    assert len(kept) == 1
    assert len(deleted) == 1


def test_dedup_source_group_short_docs_deleted():
    col = MagicMock()
    col.get.return_value = {
        "ids": ["d1", "d2"],
        "documents": ["long enough document to keep in the castle", "tiny"],
        "metadatas": [
            {"wing": "a", "source_file": "a.txt"},
            {"wing": "a", "source_file": "a.txt"},
        ],
    }
    kept, deleted = dedup.dedup_source_group(col, ["d1", "d2"], threshold=0.15, dry_run=True)
    assert "d2" in deleted


def test_dedup_source_group_empty_doc_deleted():
    col = MagicMock()
    col.get.return_value = {
        "ids": ["d1", "d2"],
        "documents": ["real document content here that is long enough", None],
        "metadatas": [
            {"wing": "a", "source_file": "a.txt"},
            {"wing": "a", "source_file": "a.txt"},
        ],
    }
    kept, deleted = dedup.dedup_source_group(col, ["d1", "d2"], threshold=0.15, dry_run=True)
    assert "d2" in deleted


def test_dedup_source_group_live_deletes():
    col = MagicMock()
    col.get.return_value = {
        "ids": ["d1", "d2"],
        "documents": ["long document content here enough", "long document content here enough"],
        "metadatas": [
            {"wing": "a", "source_file": "a.txt"},
            {"wing": "a", "source_file": "a.txt"},
        ],
    }
    col.query.return_value = {
        "ids": [["d1"]],
        "distances": [[0.05]],
    }
    kept, deleted = dedup.dedup_source_group(col, ["d1", "d2"], threshold=0.15, dry_run=False)
    col.delete.assert_called_once()
    assert kept == ["d1"]
    assert deleted == ["d2"]


def test_dedup_source_group_query_failure_keeps():
    col = MagicMock()
    col.get.return_value = {
        "ids": ["d1", "d2"],
        "documents": [
            "long document one content here enough",
            "long document two content here enough",
        ],
        "metadatas": [
            {"wing": "a", "source_file": "a.txt"},
            {"wing": "a", "source_file": "a.txt"},
        ],
    }
    col.query.side_effect = Exception("query failed")
    kept, deleted = dedup.dedup_source_group(col, ["d1", "d2"], threshold=0.15, dry_run=True)
    assert len(kept) == 2
    assert len(deleted) == 0


# ── show_stats / dedup_palace ────────────────────────────────────────


def test_show_stats_uses_storage_factory(capsys):
    factory = InMemoryStorageFactory()
    _seed_factory(factory)

    dedup.show_stats(storage_factory=factory)

    out = capsys.readouterr().out
    assert "Sources with 5+ drawers: 1" in out
    assert "src/auth.py" in out


def test_dedup_palace_dry_run_keeps_records(capsys):
    factory = InMemoryStorageFactory()
    col = _seed_factory(factory)

    dedup.dedup_palace(dry_run=True, storage_factory=factory)

    assert col.count() == 5
    out = capsys.readouterr().out
    assert "DRY RUN" in out


def test_dedup_palace_live_run_deletes_duplicates():
    factory = InMemoryStorageFactory()
    col = _seed_factory(factory)

    dedup.dedup_palace(dry_run=False, storage_factory=factory)

    assert col.count() < 5


def test_dedup_palace_with_wing_filter_only_dedups_target_wing():
    factory = InMemoryStorageFactory()
    target = _seed_factory(factory, wing="target")
    _seed_factory(factory, wing="other")

    dedup.dedup_palace(dry_run=False, wing="target", storage_factory=factory)

    result = target.get(where={"wing": "other"}, include=["documents", "metadatas"])
    assert len(result["ids"]) == 5
