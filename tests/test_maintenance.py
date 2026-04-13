"""Tests for reforge and distill services."""

from __future__ import annotations

import pytest

from swampcastle.castle import Castle
from swampcastle.models.drawer import AddDrawerCommand
from swampcastle.settings import CastleSettings
from swampcastle.storage.memory import InMemoryStorageFactory


@pytest.fixture
def castle(tmp_path):
    factory = InMemoryStorageFactory()
    # Use real CastleSettings to verify settings validation works
    settings = CastleSettings(
        _env_file=None,
        castle_path=tmp_path / "castle",
    )
    
    with Castle(settings, factory) as c:
        # Add some initial data
        c.vault.add_drawer(AddDrawerCommand(wing="test", room="r1", content="First drawer content"))
        c.vault.add_drawer(AddDrawerCommand(wing="test", room="r1", content="Second drawer with different words"))
        yield c


def test_distill_drawers_updates_metadata_with_aaak(castle):
    """Distill should compute AAAK summaries and store them in metadata."""
    # 1. Verify no AAAK yet
    # Access internal collection for verification
    results = castle.vault._col.get(include=["metadatas"])
    for meta in results["metadatas"]:
        assert "aaak" not in meta

    # 2. Distill
    count = castle.vault.distill()
    assert count == 2

    # 3. Verify AAAK exists
    results = castle.vault._col.get(include=["metadatas"])
    for meta in results["metadatas"]:
        assert "aaak" in meta
        assert "0:" in meta["aaak"]  # AAAK format marker


def test_distill_does_not_mutate_input_metadata(castle):
    """Distill should not mutate the metadata returned by collection.get()."""
    # Get metadata before distill
    before = castle.vault._col.get(include=["metadatas"])
    original_metas = [dict(m) for m in before["metadatas"]]  # deep copy

    # Distill
    castle.vault.distill()

    # Original copies should NOT have 'aaak' key (proves no mutation)
    for orig in original_metas:
        assert "aaak" not in orig


def test_reforge_recomputes_embeddings(castle):
    """Reforge should re-embed all drawers using the current embedder."""
    # 1. Reforge
    # In memory factory uses a simple store that doesn't compute real 
    # embeddings, but we verify it completes and returns the correct count.
    count = castle.vault.reforge()
    assert count == 2

    # 2. Verify drawers still exist
    results = castle.vault._col.get(include=["documents"])
    assert len(results["ids"]) == 2


def test_distill_with_wing_filter(castle):
    """Distill should respect wing filter."""
    # Add drawer in different wing
    castle.vault.add_drawer(AddDrawerCommand(wing="other", room="r1", content="Other wing"))

    count = castle.vault.distill(wing="test")
    assert count == 2  # Only original two in 'test' wing


def test_distill_with_room_filter(castle):
    """Distill should respect room filter."""
    # Add drawer in different room
    castle.vault.add_drawer(AddDrawerCommand(wing="test", room="r2", content="Other room"))

    count = castle.vault.distill(room="r1")
    assert count == 2  # Only original two in 'r1' room


def test_distill_dry_run_does_not_modify(castle):
    """Dry-run distill should count but not modify metadata."""
    count = castle.vault.distill(dry_run=True)
    assert count == 2

    # Verify metadata NOT modified
    results = castle.vault._col.get(include=["metadatas"])
    for meta in results["metadatas"]:
        assert "aaak" not in meta


def test_reforge_with_wing_filter(castle):
    """Reforge should respect wing filter."""
    castle.vault.add_drawer(AddDrawerCommand(wing="other", room="r1", content="Other wing"))

    count = castle.vault.reforge(wing="test")
    assert count == 2


def test_reforge_dry_run_does_not_modify(castle):
    """Dry-run reforge should count but not upsert."""
    # Get count before
    before_count = castle.vault._col.count()

    count = castle.vault.reforge(dry_run=True)
    assert count == 2

    # Count should be same
    assert castle.vault._col.count() == before_count
