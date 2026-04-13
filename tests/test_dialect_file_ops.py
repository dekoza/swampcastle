"""Additional coverage for Dialect file and legacy zettel helpers."""

from __future__ import annotations

import json
from pathlib import Path

from swampcastle.dialect import Dialect


def _write_zettel_file(path: Path, *, source_file: str = "001-memory.txt") -> None:
    payload = {
        "source_file": source_file,
        "emotional_arc": "curiosity->joy",
        "zettels": [
            {
                "id": "zettel-001",
                "people": ["Alice"],
                "topics": ["memory", "ai"],
                "content": 'Alice said "we should remember this forever".',
                "emotional_weight": 0.95,
                "emotional_tone": ["joy"],
                "origin_moment": True,
                "sensitivity": "",
                "notes": "foundational pillar",
                "origin_label": "genesis",
                "title": "Project - Memory Notes",
                "date_context": "2026-01-01, morning",
            }
        ],
        "tunnels": [{"from": "zettel-001", "to": "zettel-002", "label": "follows: temporal"}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_from_config_and_save_config_roundtrip(tmp_path):
    config = tmp_path / "entities.json"
    config.write_text(json.dumps({"entities": {"Alice": "ALC"}, "skip_names": ["Bob"]}))

    dialect = Dialect.from_config(str(config))
    assert dialect.encode_entity("Alice") == "ALC"
    assert dialect.encode_entity("Bob") is None

    out = tmp_path / "saved.json"
    dialect.save_config(str(out))
    saved = json.loads(out.read_text())
    assert saved["entities"]["Alice"] == "ALC"
    assert saved["skip_names"] == ["bob"]


def test_extract_key_quote_prefers_explicit_quote():
    dialect = Dialect()
    quote = dialect.extract_key_quote(
        {
            "content": 'Alice said "I want to remember everything".',
            "origin_label": "",
            "notes": "",
            "title": "Project - Notes",
        }
    )
    assert "remember everything" in quote


def test_encode_file_and_compress_file(tmp_path):
    dialect = Dialect(entities={"Alice": "ALC"})
    zettel_file = tmp_path / "file_001.json"
    _write_zettel_file(zettel_file)

    encoded = dialect.compress_file(str(zettel_file))

    assert "001|ALC" in encoded
    assert "ARC:curiosity->joy" in encoded
    assert "T:001<->002|follows" in encoded


def test_compress_all_writes_combined_output(tmp_path):
    dialect = Dialect(entities={"Alice": "ALC"})
    _write_zettel_file(tmp_path / "file_001.json", source_file="001-a.txt")
    _write_zettel_file(tmp_path / "file_002.json", source_file="002-b.txt")

    output = tmp_path / "all.aaak"
    combined = dialect.compress_all(str(tmp_path), str(output))

    assert "---" in combined
    assert output.read_text() == combined


def test_generate_layer1_writes_essential_story(tmp_path):
    dialect = Dialect(entities={"Alice": "ALC"})
    _write_zettel_file(tmp_path / "file_001.json")

    output = tmp_path / "LAYER1.aaak"
    result = dialect.generate_layer1(
        str(tmp_path),
        output_path=str(output),
        identity_sections={"WHO": ["I am SwampCastle"]},
    )

    assert "## LAYER 1 -- ESSENTIAL STORY" in result
    assert "=WHO=" in result
    assert "=MOMENTS[2026-01-01]=" in result
    assert output.read_text() == result


def test_decode_reads_header_arc_and_tunnels():
    decoded = Dialect().decode(
        "001|ALC|2026-01-01|title\n"
        "ARC:joy->wonder\n"
        '001:ALC|memory|"quote"|0.9|joy\n'
        "T:001<->002|follows"
    )

    assert decoded["header"]["title"] == "title"
    assert decoded["arc"] == "joy->wonder"
    assert decoded["tunnels"] == ["T:001<->002|follows"]
