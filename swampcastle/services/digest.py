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

# Fixed per-section budgets — the cap holds by construction (charting
# decision on #24), the final trim in build_digest is only a backstop.
TOP_WINGS = 15

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


def _date(ts: str | None) -> str:
    return ts[:10] if ts else "undated"


def _global_section(castle: "Castle") -> str:
    wings = castle.catalog.list_wings().wings
    activity = castle.catalog.wing_activity()
    total = sum(wings.values())

    try:
        kg = castle.graph.kg_stats()
        kg_line = f"{kg.entities} entities · {kg.current_facts} facts (KG)"
    except Exception:
        kg_line = "KG unavailable"

    lines = ["## Castle", "", f"{total} drawers · {kg_line}"]
    if wings:
        lines.append("Top wings:")
        ranked = sorted(wings.items(), key=lambda kv: (-kv[1], kv[0]))
        for wing, count in ranked[:TOP_WINGS]:
            lines.append(f"- {wing} — {count} drawers · last {_date(activity.get(wing))}")
        overflow = len(ranked) - TOP_WINGS
        if overflow > 0:
            lines.append(f"(+{overflow} more — use list_wings)")
    return "\n".join(lines)


def build_digest(castle: "Castle", project_dir: str | None = None) -> StatusDigest:
    """Render the session digest for this castle."""
    error: str | None = None
    sections = ["# SwampCastle — session digest", _PROTOCOL_GIST]

    try:
        sections.append(_global_section(castle))
    except Exception as e:
        error = f"Partial digest: {e}"

    sections.append(_EXTENSION_POINT)
    digest = "\n\n".join(sections)
    return StatusDigest(
        digest=digest,
        castle_path=str(castle.settings.castle_path),
        error=error,
        partial=error is not None,
    )
