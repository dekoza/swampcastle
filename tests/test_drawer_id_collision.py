"""Tests for drawer ID collision bug.

Bug: AddDrawerCommand.drawer_id() hashes only the first 100 chars of content.
Two documents that share a wing, room, and identical first-100-char prefix but
differ after that position produce the same ID, so the second document is
silently dropped with reason="already_exists".

Fix: hash the full content, not a prefix.

References: docs/reviews/architecture_critical_review.md §9
"""

import pytest

from swampcastle.models.drawer import AddDrawerCommand
from swampcastle.services.vault import VaultService
from swampcastle.storage.memory import InMemoryCollectionStore
from swampcastle.wal import WalWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

COMMON_PREFIX = "A" * 100  # exactly 100 identical leading characters


def _cmd(content: str) -> AddDrawerCommand:
    return AddDrawerCommand(wing="proj", room="arch", content=content)


@pytest.fixture
def svc(tmp_path):
    col = InMemoryCollectionStore()
    wal = WalWriter(tmp_path / "wal")
    return VaultService(col, wal)


# ---------------------------------------------------------------------------
# Unit: drawer_id uniqueness
# ---------------------------------------------------------------------------


class TestDrawerIdUniqueness:
    def test_identical_content_yields_same_id(self):
        """Same content in the same wing/room must produce the same ID (dedup)."""
        cmd1 = _cmd("The auth service was replaced with JWT.")
        cmd2 = _cmd("The auth service was replaced with JWT.")
        assert cmd1.drawer_id() == cmd2.drawer_id()

    def test_different_content_yields_different_ids(self):
        """Different content must produce different IDs even without a common prefix."""
        cmd1 = _cmd("chose postgres")
        cmd2 = _cmd("chose sqlite")
        assert cmd1.drawer_id() != cmd2.drawer_id()

    def test_same_prefix_different_suffix_yields_different_ids(self):
        """The core bug: two docs sharing first 100 chars must NOT collide."""
        content_a = COMMON_PREFIX + " — variant Alpha"
        content_b = COMMON_PREFIX + " — variant Beta"
        cmd_a = _cmd(content_a)
        cmd_b = _cmd(content_b)
        assert cmd_a.drawer_id() != cmd_b.drawer_id(), (
            "drawer_id() must distinguish documents that differ only after the first 100 chars"
        )

    def test_wing_room_included_in_id(self):
        """Same content stored in different wing/room must get different IDs."""
        content = "shared content"
        cmd1 = AddDrawerCommand(wing="wing_a", room="room_x", content=content)
        cmd2 = AddDrawerCommand(wing="wing_b", room="room_x", content=content)
        assert cmd1.drawer_id() != cmd2.drawer_id()

    def test_id_is_deterministic(self):
        """Same inputs always produce the same ID."""
        cmd = _cmd("stable content")
        assert cmd.drawer_id() == cmd.drawer_id()


# ---------------------------------------------------------------------------
# Integration: VaultService stores both documents, no silent drop
# ---------------------------------------------------------------------------


class TestVaultAddDrawerNoSilentDrop:
    def test_two_docs_same_prefix_both_stored(self, svc):
        """Both documents must be stored; collection count must reach 2."""
        content_a = COMMON_PREFIX + " — Alpha payload"
        content_b = COMMON_PREFIX + " — Beta payload"

        r1 = svc.add_drawer(_cmd(content_a))
        r2 = svc.add_drawer(_cmd(content_b))

        assert r1.success is True, f"First add failed: {r1}"
        assert r2.success is True, f"Second add failed: {r2}"
        # Neither should silently pretend to be a duplicate
        assert r2.reason != "already_exists", (
            "Second document was silently dropped as a duplicate — ID collision detected"
        )
        assert r1.drawer_id != r2.drawer_id, (
            "Both documents received the same drawer_id — collision confirmed"
        )
        assert svc._col.count() == 2, f"Expected 2 drawers in collection, got {svc._col.count()}"

    def test_identical_docs_are_idempotent(self, svc):
        """Genuinely identical content must still be treated as a duplicate."""
        content = COMMON_PREFIX + " — exactly the same"
        r1 = svc.add_drawer(_cmd(content))
        r2 = svc.add_drawer(_cmd(content))

        assert r1.success is True
        assert r2.success is True
        assert r2.reason == "already_exists"
        assert svc._col.count() == 1

    def test_three_docs_same_prefix_all_stored(self, svc):
        """Stress: three docs sharing prefix — all three must land separately."""
        docs = [COMMON_PREFIX + f" — doc_{i}" for i in range(3)]
        ids = []
        for content in docs:
            r = svc.add_drawer(_cmd(content))
            assert r.success is True
            assert r.reason != "already_exists"
            ids.append(r.drawer_id)

        assert len(set(ids)) == 3, "All three drawer IDs must be distinct"
        assert svc._col.count() == 3
