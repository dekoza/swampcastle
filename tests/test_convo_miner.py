import json
import os
import shutil
import tempfile
from pathlib import Path

from swampcastle.mining.convo import mine_convos
from swampcastle.storage.lance import LanceBackend
from swampcastle.storage.memory import InMemoryStorageFactory


def _get_test_collection(path, name="swampcastle_chests"):
    return LanceBackend().get_collection(path, name, create=True)


def test_convo_mining():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    palace_path = os.path.join(tmpdir, "palace")
    mine_convos(tmpdir, palace_path, wing="test_convos")

    col = _get_test_collection(palace_path)
    assert col.count() >= 2

    # Verify search works
    results = col.query(query_texts=["memory persistence"], n_results=1)
    assert len(results["documents"][0]) > 0

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_convo_mining_accepts_storage_factory():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    factory = InMemoryStorageFactory()
    mine_convos(tmpdir, os.path.join(tmpdir, "palace"), wing="test_convos", storage_factory=factory)

    col = factory.open_collection("swampcastle_chests")
    assert col.count() >= 2

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_convo_mining_tags_contributor_metadata():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n\n> How do we build it?\nWith structured storage.\n"
        )

    with open(os.path.join(tmpdir, ".swampcastle.yaml"), "w") as f:
        import yaml

        yaml.dump({"wing": "test_convos", "team": ["dekoza", "sarah"]}, f)

    factory = InMemoryStorageFactory()
    from unittest.mock import patch

    with patch(
        "swampcastle.mining.contributor._git_last_author",
        return_value="dekoza",
    ):
        mine_convos(
            tmpdir, os.path.join(tmpdir, "palace"), wing="test_convos", storage_factory=factory
        )

    col = factory.open_collection("swampcastle_chests")
    rows = col.get(include=["metadatas"])
    assert rows["metadatas"]
    assert all(meta.get("contributor") == "dekoza" for meta in rows["metadatas"])

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_convo_mining_can_extract_kg_proposals():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
        f.write(
            "> Why did we change auth?\nWe switched from Auth0 to Clerk because local testing got simpler.\n"
        )

    factory = InMemoryStorageFactory()
    try:
        mine_convos(
            tmpdir,
            os.path.join(tmpdir, "palace"),
            wing="test_convos",
            storage_factory=factory,
            extract_kg_proposals=True,
        )

        graph = factory.open_graph()
        proposals = graph.list_candidate_triples(status="proposed")
        assert len(proposals) >= 2
        predicates = {(row["predicate"], row["object_text"]) for row in proposals}
        assert ("migrated_from", "Auth0") in predicates
        assert ("migrated_to", "Clerk") in predicates
        assert graph.query_entity(name="test_convos", direction="outgoing") == []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_convo_mining_accepts_single_transcript_file(tmp_path):
    transcript = tmp_path / "chat.txt"
    transcript.write_text(
        "> What is memory?\nMemory is persistence.\n\n> Why does it matter?\nIt enables continuity.\n",
        encoding="utf-8",
    )

    factory = InMemoryStorageFactory()

    mine_convos(
        str(transcript),
        str(tmp_path / "palace"),
        wing="single_file",
        storage_factory=factory,
    )

    col = factory.open_collection("swampcastle_chests")
    rows = col.get(where={"source_file": str(transcript)}, include=["documents", "metadatas"])
    assert rows["ids"]
    assert all(meta["source_file"] == str(transcript) for meta in rows["metadatas"])


def test_convo_mining_reingests_changed_transcript_and_replaces_old_drawers(tmp_path):
    transcript = tmp_path / "chat.txt"
    transcript.write_text(
        "> Why did we change auth?\nWe switched from Auth0 because local testing was painful.\n",
        encoding="utf-8",
    )

    factory = InMemoryStorageFactory()
    palace_path = str(tmp_path / "palace")

    mine_convos(str(transcript), palace_path, wing="reingest", storage_factory=factory)

    transcript.write_text(
        "> Why did we change auth?\nWe switched to Clerk because local testing got simpler.\n",
        encoding="utf-8",
    )

    mine_convos(str(transcript), palace_path, wing="reingest", storage_factory=factory)

    col = factory.open_collection("swampcastle_chests")
    rows = col.get(where={"source_file": str(transcript)}, include=["documents", "metadatas"])

    assert rows["ids"]
    combined = "\n".join(rows["documents"])
    assert "Clerk" in combined
    assert "Auth0" not in combined
    assert all(meta.get("source_mtime") for meta in rows["metadatas"])


def test_convo_mining_writes_origin_manifest_and_metadata(tmp_path):
    transcript = tmp_path / "claude-session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "human",
                        "message": {"content": "hello, can you help with auth migration?"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": "Yes, let's keep working through the migration plan."
                        },
                    }
                ),
                json.dumps({"type": "human", "message": {"content": "why auth"}}),
                json.dumps({"type": "assistant", "message": {"content": "because local testing"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    factory = InMemoryStorageFactory()
    palace_path = Path(tmp_path / "palace")

    mine_convos(str(transcript), str(palace_path), wing="origin_test", storage_factory=factory)

    col = factory.open_collection("swampcastle_chests")
    rows = col.get(where={"source_file": str(transcript)}, include=["metadatas"])
    assert rows["metadatas"]

    origin_ids = {meta.get("origin_id") for meta in rows["metadatas"]}
    assert len(origin_ids) == 1
    origin_id = origin_ids.pop()
    assert origin_id
    assert all(meta.get("source_kind") == "conversation_export" for meta in rows["metadatas"])
    assert all(meta.get("source_platform") == "claude-code" for meta in rows["metadatas"])
    assert all(meta.get("origin_confidence") == "heuristic" for meta in rows["metadatas"])

    origin_path = palace_path / ".swampcastle" / "origin" / f"{origin_id}.json"
    assert origin_path.is_file()
    payload = json.loads(origin_path.read_text(encoding="utf-8"))
    assert payload["source_file"] == str(transcript)
    assert payload["source_kind"] == "conversation_export"
    assert payload["platform"] == "claude-code"
    assert payload["declared_transformations"] == ["jsonl_normalize"]


def test_convo_mining_uses_curation_wing_hint_when_wing_is_unspecified(tmp_path):
    transcript = tmp_path / "exports" / "claude-session-001.jsonl"
    transcript.parent.mkdir()
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "human",
                        "message": {"content": "hello, can you help with auth migration?"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": "Yes, let's keep working through the migration plan."
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    palace_path = Path(tmp_path / "palace")
    curation_dir = palace_path / ".swampcastle" / "curation"
    curation_dir.mkdir(parents=True)
    (curation_dir / "aliases.yaml").write_text(
        "wing_hints:\n  claude-session: hinted_wing\n",
        encoding="utf-8",
    )

    factory = InMemoryStorageFactory()

    mine_convos(str(transcript), str(palace_path), storage_factory=factory)

    col = factory.open_collection("swampcastle_chests")
    rows = col.get(where={"source_file": str(transcript)}, include=["metadatas"])
    assert rows["metadatas"]
    assert all(meta.get("wing") == "hinted_wing" for meta in rows["metadatas"])
