"""Source-origin detection and manifest persistence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from swampcastle.mining.normalize import (
    _try_chatgpt_json,
    _try_claude_ai_json,
    _try_claude_code_jsonl,
    _try_codex_jsonl,
    _try_slack_json,
)
from swampcastle.models.origin import SourceOrigin


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_text(source_file: str | Path) -> str:
    path = Path(source_file).expanduser()
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _origin_id_for_source(source_file: str | None) -> str:
    seed = source_file or "unknown"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"origin_{digest}"


def _detect_platform_and_transformations(content: str) -> tuple[str | None, list[str]]:
    if _try_claude_code_jsonl(content):
        return "claude-code", ["jsonl_normalize"]
    if _try_codex_jsonl(content):
        return "codex", ["jsonl_normalize"]

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None, []

    if _try_claude_ai_json(parsed):
        return "claude-ai", ["json_normalize"]
    if _try_chatgpt_json(parsed):
        return "chatgpt", ["json_normalize"]
    if _try_slack_json(parsed):
        return "slack", ["json_normalize"]
    return None, []


def detect_source_origin(source_file: str | Path) -> SourceOrigin:
    resolved = str(Path(source_file).expanduser().resolve())
    content = _read_text(resolved)
    platform, transformations = _detect_platform_and_transformations(content)

    source_kind = "unknown"
    if Path(resolved).suffix.lower() in {".txt", ".md", ".json", ".jsonl"}:
        source_kind = "conversation_export"

    return SourceOrigin(
        origin_id=_origin_id_for_source(resolved),
        source_kind=source_kind,
        platform=platform,
        declared_transformations=transformations,
        confidence="heuristic",
        source_file=resolved,
        updated_at=_utc_now_iso(),
    )


def origin_manifest_path(castle_path: str | Path, origin_id: str) -> Path:
    castle_dir = Path(castle_path).expanduser().resolve()
    return castle_dir / ".swampcastle" / "origin" / f"{origin_id}.json"


def write_origin_manifest(castle_path: str | Path, origin: SourceOrigin) -> Path:
    manifest_path = origin_manifest_path(castle_path, origin.origin_id)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = manifest_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(origin.model_dump(), handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(manifest_path)
    return manifest_path


def load_origin_manifest(castle_path: str | Path, origin_id: str) -> SourceOrigin | None:
    manifest_path = origin_manifest_path(castle_path, origin_id)
    if not manifest_path.is_file():
        return None
    with open(manifest_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return SourceOrigin.model_validate(payload)


def origin_metadata(origin: SourceOrigin) -> dict[str, str]:
    metadata = {
        "origin_id": origin.origin_id,
        "source_kind": origin.source_kind,
        "origin_confidence": origin.confidence,
    }
    if origin.platform:
        metadata["source_platform"] = origin.platform
    return metadata
