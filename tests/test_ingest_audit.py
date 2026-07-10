"""Regression tests for the ingest-correctness audit (wayfinder ticket #20).

Each test class pins one upstream bug-ledger item (docs/research/mempalace-delta.md
§4) against swampcastle/mining/. Upstream issue numbers in class docstrings.
"""

import json

from swampcastle.mining import convo as convo_mod
from swampcastle.mining import miner as miner_mod
from swampcastle.mining.convo import (
    _file_already_mined,
    _purge_source_file,
    chunk_exchanges,
    scan_convos,
)
from swampcastle.mining.miner import _name_matches, detect_room
from swampcastle.mining.normalize import (
    _try_claude_code_jsonl,
    _try_pi_jsonl,
    strip_noise,
)

# =============================================================================
# #708 / #695 — full AI response preserved (was: 8-line space-joined truncation)
# =============================================================================


class TestFullAIResponse:
    def _transcript(self, n_lines: int) -> str:
        ai_lines = [f"Response line {i} with enough substance to matter." for i in range(n_lines)]
        return "> What happened?\n" + "\n".join(ai_lines) + "\n\n> Next?\nShort answer here.\n"

    def test_ai_response_beyond_8_lines_is_preserved(self):
        chunks = chunk_exchanges(self._transcript(30))
        joined = "\n".join(c["content"] for c in chunks)
        for i in range(30):
            assert f"Response line {i} " in joined, f"line {i} dropped"

    def test_ai_response_line_structure_preserved(self):
        """Lines join on newline, not space — structure carries meaning."""
        content = "> Q?\nFirst line.\nSecond line.\nThird line is long enough to keep.\n"
        chunks = chunk_exchanges(content)
        assert len(chunks) == 1
        assert "First line.\nSecond line." in chunks[0]["content"]


# =============================================================================
# #1538 / #1554 — bounded emission, no per-file cap dropping tails
# =============================================================================


class TestBoundedChunks:
    def test_no_chunk_exceeds_chunk_size(self):
        big_response = "word " * 2000  # ~10K chars, one paragraph
        content = f"> Question?\n{big_response}\n\n> Follow-up?\nAnother answer here.\n"
        chunks = chunk_exchanges(content)
        assert all(len(c["content"]) <= convo_mod.CHUNK_SIZE for c in chunks)

    def test_paragraph_chunker_bounds_long_paragraphs(self):
        content = ("word " * 2000).strip()  # no > markers, no paragraph breaks, few newlines
        chunks = convo_mod._chunk_by_paragraph(content)
        assert chunks, "long paragraph produced no chunks"
        assert all(len(c["content"]) <= convo_mod.CHUNK_SIZE for c in chunks)

    def test_small_trailing_remainder_preserved(self):
        """Once content passes the floor, every slice is emitted — even a short tail."""
        content = "x" * (convo_mod.CHUNK_SIZE + 10)
        chunks: list = []
        convo_mod._emit_bounded(chunks, content)
        assert sum(len(c["content"]) for c in chunks) == len(content)

    def test_no_per_file_chunk_cap(self):
        exchanges = "".join(
            f"> Question number {i}?\nAnswer number {i} with enough length to pass the floor.\n\n"
            for i in range(200)
        )
        chunks = chunk_exchanges(exchanges)
        joined = "\n".join(c["content"] for c in chunks)
        assert "Question number 199?" in joined, "transcript tail dropped"


# =============================================================================
# #998 — oversize transcript files mined, not silently skipped
# =============================================================================


class TestOversizeFiles:
    def test_size_cap_matches_normalize_safety_limit(self):
        assert convo_mod.MAX_FILE_SIZE == 500 * 1024 * 1024
        assert miner_mod.MAX_FILE_SIZE == 500 * 1024 * 1024

    def test_scan_convos_accepts_file_over_10mb(self, tmp_path):
        big = tmp_path / "session.jsonl"
        with open(big, "wb") as f:
            f.seek(15 * 1024 * 1024)  # sparse — st_size is what the gate reads
            f.write(b"x")
        files = scan_convos(str(tmp_path))
        assert big in files


# =============================================================================
# #1004 — separator-bounded room matching (was: "views" routed to "interviews")
# =============================================================================


class TestNameMatches:
    def test_incidental_substring_does_not_match(self):
        assert not _name_matches("views", "interviews")
        assert not _name_matches("interviews", "views")

    def test_separator_bounded_token_matches(self):
        assert _name_matches("frontend", "frontend-app")
        assert _name_matches("frontend-app", "frontend")

    def test_exact_match(self):
        assert _name_matches("docs", "docs")


class TestDetectRoomRouting:
    ROOMS = [
        {"name": "interviews", "keywords": []},
        {"name": "views", "keywords": []},
    ]

    def test_views_dir_not_routed_to_interviews(self, tmp_path):
        views_dir = tmp_path / "views"
        views_dir.mkdir()
        f = views_dir / "layout.md"
        f.write_text("some content")
        room = detect_room(f, "some content", [self.ROOMS[0]], tmp_path)
        assert room != "interviews"

    def test_exact_dir_still_routes(self, tmp_path):
        views_dir = tmp_path / "views"
        views_dir.mkdir()
        f = views_dir / "layout.md"
        f.write_text("some content")
        room = detect_room(f, "some content", self.ROOMS, tmp_path)
        assert room == "views"


# =============================================================================
# #1528 — mode-scoped dedup (registry drawers must not block convo mining)
# =============================================================================


class FakeCollection:
    def __init__(self):
        self.rows = {}

    def upsert(self, documents, ids, metadatas):
        for doc, id_, meta in zip(documents, ids, metadatas):
            self.rows[id_] = {"document": doc, "metadata": meta}

    def _matches(self, meta, where):
        if "$and" in where:
            return all(self._matches(meta, clause) for clause in where["$and"])
        return all(meta.get(k) == v for k, v in where.items())

    def get(self, where=None, ids=None, limit=None, include=None):
        found_ids, metas = [], []
        for id_, row in self.rows.items():
            if ids is not None and id_ not in ids:
                continue
            if where and not self._matches(row["metadata"], where):
                continue
            found_ids.append(id_)
            metas.append(row["metadata"])
            if limit and len(found_ids) >= limit:
                break
        return {"ids": found_ids, "metadatas": metas}

    def delete(self, ids):
        for id_ in ids:
            self.rows.pop(id_, None)


class TestModeScopedDedup:
    def test_registry_drawer_does_not_block_convo_check(self):
        coll = FakeCollection()
        coll.upsert(
            documents=["registry content"],
            ids=["drawer_x_general_abc"],
            metadatas=[{"source_file": "/p/notes.md", "ingest_mode": "registry"}],
        )
        assert _file_already_mined(coll, "/p/notes.md") is False

    def test_convo_drawer_still_detected(self):
        coll = FakeCollection()
        coll.upsert(
            documents=["convo content"],
            ids=["drawer_x_general_def"],
            metadatas=[{"source_file": "/p/notes.md", "ingest_mode": "convos"}],
        )
        assert _file_already_mined(coll, "/p/notes.md") is True

    def test_purge_leaves_registry_drawers(self):
        coll = FakeCollection()
        coll.upsert(
            documents=["registry content", "convo content"],
            ids=["reg1", "con1"],
            metadatas=[
                {"source_file": "/p/notes.md", "ingest_mode": "registry"},
                {"source_file": "/p/notes.md", "ingest_mode": "convos"},
            ],
        )
        _purge_source_file(coll, "/p/notes.md")
        assert "reg1" in coll.rows
        assert "con1" not in coll.rows

    def test_registry_writes_stamp_ingest_mode(self):
        coll = FakeCollection()
        miner_mod.add_drawer(
            collection=coll,
            wing="w",
            room="general",
            content="some chunk content",
            source_file="/p/file.py",
            chunk_index=0,
            agent="test",
        )
        (meta,) = [r["metadata"] for r in coll.rows.values()]
        assert meta["ingest_mode"] == "registry"


# =============================================================================
# #785 — noise stripping of system tags and hook chrome
# =============================================================================


class TestStripNoise:
    def test_system_reminder_tag_removed(self):
        text = "Real question here.\n<system-reminder>\ninjected context\n</system-reminder>\nMore prose."
        result = strip_noise(text)
        assert "injected context" not in result
        assert "Real question here." in result
        assert "More prose." in result

    def test_tag_with_attributes_removed(self):
        text = '<system-reminder priority="high">noise</system-reminder>\nkeep me'
        result = strip_noise(text)
        assert "noise" not in result
        assert "keep me" in result

    def test_blockquoted_tag_removed(self):
        text = "> <system-reminder>injected</system-reminder>\n> real user words"
        result = strip_noise(text)
        assert "injected" not in result
        assert "real user words" in result

    def test_unclosed_tag_does_not_eat_across_blank_lines(self):
        text = "<system-reminder>\ndangling open tag\n\nThis paragraph must survive."
        result = strip_noise(text)
        assert "This paragraph must survive." in result

    def test_hook_chrome_line_removed(self):
        text = "Ran 2 Stop hooks\nActual content stays."
        result = strip_noise(text)
        assert "Ran 2 Stop hooks" not in result
        assert "Actual content stays." in result

    def test_collapsed_lines_marker_removed(self):
        text = "… +47 lines (ctrl+o to expand)\nVisible content."
        result = strip_noise(text)
        assert "+47 lines" not in result
        assert "Visible content." in result

    def test_token_chrome_removed(self):
        text = "Read the file [1234 tokens] (ctrl+o to expand) and moved on."
        result = strip_noise(text)
        assert "[1234 tokens]" not in result
        assert "Read the file" in result
        assert "and moved on." in result

    def test_inline_prose_mention_preserved(self):
        text = "The harness injects system-reminder tags into every message."
        assert strip_noise(text) == text

    def test_applied_in_claude_code_parser(self):
        lines = [
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": "<system-reminder>injected noise</system-reminder>\nreal question",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": "real answer"},
                }
            ),
            json.dumps(
                {
                    "type": "user",
                    "message": {"role": "user", "content": "second question"},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": "second answer"},
                }
            ),
        ]
        result = _try_claude_code_jsonl("\n".join(lines))
        assert result is not None
        assert "injected noise" not in result
        assert "real question" in result

    def test_message_emptied_by_stripping_is_dropped(self):
        lines = [
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": "<system-reminder>only noise</system-reminder>",
                    },
                }
            ),
            json.dumps({"type": "user", "message": {"role": "user", "content": "real question"}}),
            json.dumps(
                {"type": "assistant", "message": {"role": "assistant", "content": "real answer"}}
            ),
        ]
        result = _try_claude_code_jsonl("\n".join(lines))
        assert result is not None
        assert "only noise" not in result
        # the all-noise message must not leave an empty "> " turn behind
        assert "> real question" in result

    def test_applied_in_pi_parser(self):
        lines = [
            json.dumps({"type": "session", "version": 1, "id": "s1"}),
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "user",
                        "content": "<system-reminder>pi noise</system-reminder>\npi question",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "message",
                    "message": {"role": "assistant", "content": "pi answer"},
                }
            ),
        ]
        result = _try_pi_jsonl("\n".join(lines))
        assert result is not None
        assert "pi noise" not in result
        assert "pi question" in result
