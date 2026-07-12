"""Tests for the session digest — the capped payload `status` returns (#24)."""

import pytest

from swampcastle.castle import Castle
from swampcastle.services.digest import DIGEST_MAX_BYTES, DIGEST_MAX_LINES, build_digest
from swampcastle.settings import CastleSettings
from swampcastle.storage.memory import InMemoryStorageFactory


@pytest.fixture
def castle(tmp_path):
    settings = CastleSettings(castle_path=tmp_path / "castle", _env_file=None)
    with Castle(settings, InMemoryStorageFactory()) as c:
        yield c


class TestProtocolGist:
    def test_empty_castle_digest_carries_gist_and_extension_point(self, castle):
        result = build_digest(castle)

        digest = result.digest
        # Read-first discipline stated up front
        assert "query first" in digest.lower()
        # Zoom tools named client-agnostically
        for tool in ("search", "get_taxonomy", "get_aaak_spec", "list_wings"):
            assert tool in digest
        # The stale hardcoded prefix must be gone
        assert "swampcastle_" not in digest
        # Marked extension point for milestone D's core-memory blocks
        assert "<!-- extension point: core-memory blocks" in digest

        assert result.partial is False
        assert len(digest.splitlines()) <= DIGEST_MAX_LINES
        assert len(digest.encode("utf-8")) <= DIGEST_MAX_BYTES
