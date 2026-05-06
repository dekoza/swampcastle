"""Tests for source-origin detection and manifest persistence."""

from __future__ import annotations

import json

from swampcastle.audit.origin import (
    detect_source_origin,
    load_origin_manifest,
    write_origin_manifest,
)
from swampcastle.models.origin import SourceOrigin


def test_detect_source_origin_for_claude_code_jsonl(tmp_path):
    transcript = tmp_path / "claude-session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "human", "message": {"content": "hello"}}),
                json.dumps({"type": "assistant", "message": {"content": "hi"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    origin = detect_source_origin(str(transcript))

    assert origin.source_kind == "conversation_export"
    assert origin.platform == "claude-code"
    assert origin.declared_transformations == ["jsonl_normalize"]
    assert origin.confidence == "heuristic"
    assert origin.source_file == str(transcript)


def test_detect_source_origin_for_codex_jsonl(tmp_path):
    transcript = tmp_path / "rollout.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "session_meta", "payload": {"id": "s1"}}),
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "hello"},
                    }
                ),
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {"type": "agent_message", "message": "hi"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    origin = detect_source_origin(str(transcript))

    assert origin.source_kind == "conversation_export"
    assert origin.platform == "codex"
    assert origin.declared_transformations == ["jsonl_normalize"]


def test_origin_manifest_round_trip(tmp_path):
    origin = SourceOrigin(
        origin_id="origin_test_123",
        source_kind="conversation_export",
        platform="claude-code",
        user_name=None,
        agent_personas=[],
        declared_transformations=["jsonl_normalize"],
        confidence="heuristic",
        source_file="/tmp/session.jsonl",
        updated_at="2026-05-07T12:00:00Z",
    )

    write_origin_manifest(tmp_path / "castle", origin)
    loaded = load_origin_manifest(tmp_path / "castle", origin.origin_id)

    assert loaded is not None
    assert loaded.model_dump() == origin.model_dump()
