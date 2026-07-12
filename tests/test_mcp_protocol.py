"""Tests for the MCP server instructions — the protocol's primary home (#25)."""

import re

from swampcastle.mcp.protocol import SERVER_INSTRUCTIONS
from swampcastle.mcp.tools import CANONICAL_TOOL_NAMES, LEGACY_TOOL_ALIASES


class TestServerInstructions:
    def test_every_canonical_tool_documented_bare(self):
        """Every registered tool must appear by its client-agnostic bare name."""
        missing = [
            name
            for name in CANONICAL_TOOL_NAMES
            if not re.search(rf"\b{re.escape(name)}\b", SERVER_INSTRUCTIONS)
        ]
        assert not missing, f"Missing from SERVER_INSTRUCTIONS: {missing}"

    def test_no_stale_legacy_tool_names(self):
        """The old text hardcoded swampcastle_search etc. — never again.
        (The mcp__swampcastle__ prefix *example* is fine; the legacy
        swampcastle_<tool> alias forms are not.)"""
        stale = [alias for alias in LEGACY_TOOL_ALIASES if alias in SERVER_INSTRUCTIONS]
        assert not stale, f"legacy tool names in instructions: {stale}"

    def test_ordering_language_present(self):
        text = SERVER_INSTRUCTIONS.lower()
        assert "call status first" in text
        assert "before any task work" in text

    def test_core_discipline_kept(self):
        assert "Query first" in SERVER_INSTRUCTIONS
        assert "do not guess" in SERVER_INSTRUCTIONS
        assert "check_duplicate" in SERVER_INSTRUCTIONS
        assert "kg_invalidate" in SERVER_INSTRUCTIONS

    def test_compact_enough_for_client_context(self):
        """Instructions land in every session's context — keep them lean."""
        assert len(SERVER_INSTRUCTIONS.encode("utf-8")) <= 4096


class TestInitializeCarriesInstructions:
    def test_initialize_result_has_instructions(self, tmp_path):
        from swampcastle.castle import Castle
        from swampcastle.mcp.server import create_handler
        from swampcastle.settings import CastleSettings
        from swampcastle.storage.memory import InMemoryStorageFactory

        settings = CastleSettings(castle_path=tmp_path / "castle", _env_file=None)
        with Castle(settings, InMemoryStorageFactory()) as castle:
            handler = create_handler(castle)
            resp = handler(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05"},
                }
            )
        assert resp["result"]["instructions"] == SERVER_INSTRUCTIONS
