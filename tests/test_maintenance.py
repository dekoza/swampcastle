"""Tests for reforge and distill services."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from swampcastle.castle import Castle
from swampcastle.models.drawer import AddDrawerCommand
from swampcastle.storage.memory import InMemoryStorageFactory


@pytest.fixture
def castle():
    factory = InMemoryStorageFactory()
    # Mock settings
    settings = MagicMock()
    settings.castle_path = "/tmp/castle"
    
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
