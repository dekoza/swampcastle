"""Per-session protocol-adherence instrumentation for the MCP server.

Server-side, zero client cooperation: one JSON record per MCP session,
atomically rewritten on every tool call so a killed server loses nothing
but its `ended_at` stamp. Metrics are derived from the raw call sequence
at query time, keeping the recorder dumb and the semantics in one pure
function.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("swampcastle.adherence")

# Tool classification for ordering metrics. Read = consults memory before
# acting; write = files something into it. Tools absent from both sets
# (e.g. delete_drawer, record GC) count toward totals but not ordering.
READ_TOOLS = frozenset(
    {
        "status",
        "search",
        "check_duplicate",
        "kg_query",
        "kg_timeline",
        "kg_stats",
        "list_wings",
        "list_rooms",
        "get_taxonomy",
        "get_aaak_spec",
        "get_origin",
        "get_curation",
        "list_catalog_cards",
        "traverse",
        "find_tunnels",
        "graph_stats",
        "diary_read",
        "record_get",
        "record_gc_status",
    }
)
WRITE_TOOLS = frozenset(
    {
        "checkpoint",
        "add_drawer",
        "diary_write",
        "kg_add",
        "kg_invalidate",
        "record_add",
    }
)
# Writes that close the session's write path ("file this session").
SESSION_FILING_TOOLS = frozenset({"checkpoint", "diary_write"})


def derive_metrics(record: dict) -> dict:
    """Compute adherence metrics from a raw session record.

    - read_before_write: did any read-tool call precede the first write?
      None when the session never wrote.
    - checkpoint_at_end: was the session's *last* write a session-filing
      write (checkpoint/diary_write)? None when the session never wrote.
    """
    tools = [c["tool"] for c in record.get("calls", [])]
    write_calls = [t for t in tools if t in WRITE_TOOLS]

    if write_calls:
        first_write_index = next(i for i, t in enumerate(tools) if t in WRITE_TOOLS)
        read_before_write = any(t in READ_TOOLS for t in tools[:first_write_index])
        checkpoint_at_end = write_calls[-1] in SESSION_FILING_TOOLS
    else:
        read_before_write = None
        checkpoint_at_end = None

    return {
        "total_calls": len(tools),
        "status_called": "status" in tools,
        "search_called": "search" in tools,
        "read_before_write": read_before_write,
        "checkpoint_at_end": checkpoint_at_end,
        "last_tool": tools[-1] if tools else None,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sessions_dir_for_castle(castle_path: str) -> Path:
    return Path(castle_path).expanduser().resolve() / ".swampcastle" / "adherence" / "sessions"


def load_sessions(castle_path: str, limit: int = 20) -> list[dict]:
    """Load raw session records, most recent first. Corrupt files are skipped."""
    sessions_dir = sessions_dir_for_castle(castle_path)
    if not sessions_dir.is_dir():
        return []
    records = []
    for path in sessions_dir.glob("*.json"):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            logger.warning("adherence: skipping unreadable session file %s", path)
    records.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return records[:limit]


class AdherenceRecorder:
    """Records one MCP session's tool-call activity to a JSON file.

    Every public method swallows exceptions: instrumentation must never
    take the server down or fail a tool call.
    """

    def __init__(self, sessions_dir: Path):
        self._dir = Path(sessions_dir)
        self._record: dict | None = None
        self._path: Path | None = None

    @classmethod
    def for_castle(cls, castle_path: str) -> "AdherenceRecorder":
        return cls(sessions_dir_for_castle(castle_path))

    def session_started(self, client_info: dict | None = None) -> None:
        try:
            started_at = _utc_now_iso()
            session_id = (
                started_at.replace(":", "").replace("-", "")[:15] + "-" + uuid.uuid4().hex[:8]
            )
            client_info = client_info or {}
            self._record = {
                "session_id": session_id,
                "started_at": started_at,
                "ended_at": None,
                "client_name": client_info.get("name"),
                "client_version": client_info.get("version"),
                "project_dir": None,
                "calls": [],
                "counts": {},
            }
            self._path = self._dir / f"{session_id}.json"
            self._persist()
        except Exception:
            logger.warning("adherence: session_started failed", exc_info=True)

    def record_call(self, tool_name: str, arguments: dict | None = None) -> None:
        if self._record is None:
            return
        try:
            self._record["calls"].append({"tool": tool_name, "at": _utc_now_iso()})
            counts = self._record["counts"]
            counts[tool_name] = counts.get(tool_name, 0) + 1
            if tool_name == "status" and self._record["project_dir"] is None:
                self._record["project_dir"] = (arguments or {}).get("project_dir")
            self._persist()
        except Exception:
            logger.warning("adherence: record_call failed", exc_info=True)

    def session_ended(self) -> None:
        if self._record is None:
            return
        try:
            self._record["ended_at"] = _utc_now_iso()
            self._persist()
        except Exception:
            logger.warning("adherence: session_ended failed", exc_info=True)

    def _persist(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._record, indent=1), encoding="utf-8")
        os.replace(tmp, self._path)
