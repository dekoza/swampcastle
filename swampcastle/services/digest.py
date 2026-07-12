"""Session digest — the capped markdown payload the `status` tool returns.

Designed for verbatim injection at session start (SessionStart hook,
ticket #26); the same text serves agents calling `status` mid-session.
Structured data stays behind the zoom tools (get_taxonomy, list_wings,
kg_stats, ...). Hard cap: DIGEST_MAX_LINES / DIGEST_MAX_BYTES — met by
per-section budgets, with a defensive trim as the final backstop.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from swampcastle.models.catalog import StatusDigest
from swampcastle.project_config import resolve_project_config

if TYPE_CHECKING:
    from swampcastle.castle import Castle

DIGEST_MAX_LINES = 200
DIGEST_MAX_BYTES = 25 * 1024

# Fixed per-section budgets — the cap holds by construction (charting
# decision on #24), the final trim in build_digest is only a backstop.
TOP_WINGS = 15
TOP_ROOMS = 10

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


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _resolve_project_wings(project_dir: str, all_wings: dict[str, int]) -> list[str]:
    """Wings belonging to a project: .swampcastle.yaml wing + path-slug siblings.

    Transcript mining names wings after the project path (slugified,
    lowercased), so one project's memories span the config wing and any
    slug variants; the digest merges them (charting decision on #24).
    """
    wings: list[str] = []

    config_path = resolve_project_config(project_dir)
    if config_path is not None:
        try:
            import yaml

            config = yaml.safe_load(config_path.read_text()) or {}
            config_wing = config.get("wing")
            if config_wing in all_wings:
                wings.append(config_wing)
        except Exception:
            pass  # unreadable config must not break the digest

    path_slug = _slug(str(Path(project_dir).expanduser().resolve()))
    for wing in all_wings:
        if _slug(wing) == path_slug and wing not in wings:
            wings.append(wing)
    return wings


def _project_section(castle: "Castle", project_dir: str) -> str | None:
    wings = castle.catalog.list_wings().wings
    project_wings = _resolve_project_wings(project_dir, wings)
    if not project_wings:
        return None

    taxonomy = castle.catalog.get_taxonomy().taxonomy
    activity = castle.catalog.wing_activity()

    total = sum(wings[w] for w in project_wings)
    last = max((activity.get(w) or "" for w in project_wings), default="") or None
    rooms: dict[str, int] = {}
    for w in project_wings:
        for room, count in taxonomy.get(w, {}).items():
            rooms[room] = rooms.get(room, 0) + count

    lines = [
        "## Project",
        "",
        f"Wings: {', '.join(project_wings)}",
        f"{total} drawers · last {_date(last)}",
    ]
    if rooms:
        lines.append("Rooms:")
        ranked = sorted(rooms.items(), key=lambda kv: (-kv[1], kv[0]))
        for room, count in ranked[:TOP_ROOMS]:
            lines.append(f"- {room} — {count}")
        overflow = len(ranked) - TOP_ROOMS
        if overflow > 0:
            lines.append(f"(+{overflow} more — use list_rooms)")
    return "\n".join(lines)


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
        if project_dir:
            project = _project_section(castle, project_dir)
            if project:
                sections.append(project)
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
