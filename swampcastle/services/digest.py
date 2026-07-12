"""Session digest — the capped markdown payload the `status` tool returns.

Designed for verbatim injection at session start (SessionStart hook,
ticket #26); the same text serves agents calling `status` mid-session.
Structured data stays behind the zoom tools (get_taxonomy, list_wings,
kg_stats, ...). Hard cap: DIGEST_MAX_LINES / DIGEST_MAX_BYTES — met by
per-section budgets, with a defensive trim as the final backstop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from swampcastle.models.catalog import StatusDigest

if TYPE_CHECKING:
    from swampcastle.castle import Castle

DIGEST_MAX_LINES = 200
DIGEST_MAX_BYTES = 25 * 1024

# Tool names written client-agnostically: clients prefix them differently
# (Claude Code: mcp__swampcastle__search), so the digest never hardcodes one.
_PROTOCOL_GIST = """\
## Memory protocol

- Never state project history, decisions, people, or prior work from memory alone — query first (`search`, `kg_query`); if results are missing or ambiguous, say so.
- Scope queries with wing/room filters; keywords, not sentences.
- Zoom tools: `get_taxonomy` (wing→room tree), `list_wings`, `list_rooms`, `kg_stats`, `kg_timeline`, `diary_read`, `get_aaak_spec` (compressed dialect used in stored text).
- Before writing: `check_duplicate`; replace stale facts via `kg_invalidate` then `kg_add`.
- End of session: file durable learnings (`add_drawer`, `diary_write`).

(Tool names may carry a client prefix, e.g. `mcp__<server>__search`.)"""

_EXTENSION_POINT = "<!-- extension point: core-memory blocks (milestone D wiki layer) -->"


def build_digest(castle: "Castle", project_dir: str | None = None) -> StatusDigest:
    """Render the session digest for this castle."""
    sections = [
        "# SwampCastle — session digest",
        _PROTOCOL_GIST,
        _EXTENSION_POINT,
    ]
    digest = "\n\n".join(sections)
    return StatusDigest(
        digest=digest,
        castle_path=str(castle.settings.castle_path),
    )
