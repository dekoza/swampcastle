"""Tests for the internal mining adapter seam."""

from __future__ import annotations

import yaml

from swampcastle.models.origin import SourceOrigin


def _write_project_config(project_root, *, wing="test_project"):
    (project_root / ".swampcastle.yaml").write_text(
        yaml.safe_dump(
            {
                "wing": wing,
                "rooms": [
                    {"name": "backend", "description": "Backend code"},
                    {"name": "general", "description": "General"},
                ],
            }
        ),
        encoding="utf-8",
    )


def test_project_and_conversation_adapters_expose_declared_transformations():
    from swampcastle.mining.adapters import ConversationExportsAdapter, ProjectFilesAdapter

    assert ProjectFilesAdapter.name == "project_files"
    assert ProjectFilesAdapter.declared_transformations == ()

    assert ConversationExportsAdapter.name == "conversation_exports"
    assert ConversationExportsAdapter.declared_transformations == (
        "jsonl_normalize",
        "json_normalize",
    )


def test_project_files_adapter_scan_matches_scan_project(tmp_path):
    from swampcastle.mining.adapters import ProjectFilesAdapter
    from swampcastle.mining.miner import scan_project

    project_root = tmp_path / "project"
    (project_root / "backend").mkdir(parents=True)
    _write_project_config(project_root)
    (project_root / "backend" / "app.py").write_text("print('hello')\n" * 20, encoding="utf-8")

    adapter = ProjectFilesAdapter(project_root)
    adapter_paths = [item.path for item in adapter.scan()]
    direct_paths = scan_project(str(project_root))

    assert adapter_paths == direct_paths


def test_conversation_exports_adapter_scan_matches_scan_convos(tmp_path):
    from swampcastle.mining.adapters import ConversationExportsAdapter
    from swampcastle.mining.convo import scan_convos

    transcript = tmp_path / "exports" / "session.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"message": {"role": "user", "content": "hello"}}\n', encoding="utf-8")

    adapter = ConversationExportsAdapter(transcript)
    adapter_paths = [item.path for item in adapter.scan()]
    direct_paths = scan_convos(str(transcript))

    assert adapter_paths == direct_paths


def test_mine_uses_project_files_adapter_in_sequential_path(tmp_path, monkeypatch):
    from swampcastle.mining.adapters.base import ProjectSourceItem, ProjectSourceResult
    from swampcastle.mining.miner import mine

    project_root = tmp_path / "project"
    (project_root / "backend").mkdir(parents=True)
    _write_project_config(project_root)
    source_file = project_root / "backend" / "app.py"
    source_file.write_text("print('hello')\n" * 20, encoding="utf-8")

    calls: list[tuple[str, object]] = []

    class FakeProjectAdapter:
        name = "project_files"
        declared_transformations = ()

        def __init__(self, project_path, **kwargs):
            calls.append(("init", project_path))

        def scan(self, *, limit=0):
            calls.append(("scan", limit))
            return [ProjectSourceItem(path=source_file)]

        def ingest(self, item, **kwargs):
            calls.append(("ingest", item.path))
            return ProjectSourceResult(drawers=1, room="backend")

    monkeypatch.setattr("swampcastle.mining.miner.ProjectFilesAdapter", FakeProjectAdapter)

    mine(str(project_root), str(tmp_path / "castle"), dry_run=True, parallel_workers=1)

    assert ("scan", 0) in calls
    assert ("ingest", source_file) in calls


def test_mine_convos_uses_conversation_adapter(tmp_path, monkeypatch):
    from swampcastle.mining.adapters.base import ConversationSourceItem, ConversationSourceResult
    from swampcastle.mining.convo import mine_convos

    transcript = tmp_path / "exports" / "session.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"message": {"role": "user", "content": "hello"}}\n', encoding="utf-8")

    origin = SourceOrigin(
        origin_id="origin_test",
        source_kind="conversation_export",
        platform="claude-code",
        declared_transformations=["jsonl_normalize"],
        confidence="heuristic",
        source_file=str(transcript),
        updated_at="2026-05-07T12:00:00Z",
    )

    calls: list[tuple[str, object]] = []

    class FakeConversationAdapter:
        name = "conversation_exports"
        declared_transformations = ("jsonl_normalize", "json_normalize")

        def __init__(self, source_path, **kwargs):
            calls.append(("init", source_path))

        def scan(self, *, limit=0):
            calls.append(("scan", limit))
            return [ConversationSourceItem(path=transcript)]

        def ingest(self, item, **kwargs):
            calls.append(("ingest", item.path))
            return ConversationSourceResult(
                filepath=item.path,
                chunks=[{"content": "> hello\nhi", "chunk_index": 0}],
                room="general",
                contributor=None,
                origin=origin.model_copy(update={"source_file": str(item.path)}),
                source_mtime=None,
            )

    monkeypatch.setattr(
        "swampcastle.mining.convo.ConversationExportsAdapter", FakeConversationAdapter
    )

    mine_convos(str(transcript), str(tmp_path / "castle"), dry_run=True)

    assert ("scan", 0) in calls
    assert ("ingest", transcript) in calls
