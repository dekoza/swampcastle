"""Tests for sentence-aware chunking in miner.chunk_text()."""

from swampcastle.mining.miner import chunk_text


def test_chunk_text_prefers_sentence_boundary_for_prose_without_newlines():
    """When prose has no paragraph/line breaks, chunk_text should still avoid
    splitting mid-sentence if a sentence boundary exists in the back half of
    the chunk window.

    Old behaviour cut exactly at CHUNK_SIZE, producing chunks ending with
    partial words/sentences like '...recall. Al'.
    """
    sentence = (
        "Alpha systems need careful retrieval design because context matters "
        "deeply and every boundary split hurts recall. "
    )
    content = sentence * 10  # > CHUNK_SIZE, no newlines, plenty of sentence boundaries

    chunks = chunk_text(content, "essay.txt")

    assert len(chunks) >= 2
    first = chunks[0]["content"]

    assert first.endswith("."), f"First chunk should end at a sentence boundary, got: {first[-30:]}"


def test_chunk_text_falls_back_to_word_boundary_when_no_sentence_exists():
    """If there is no sentence boundary, avoid splitting inside a word."""
    token = "supercalifragilisticexpialidocious "
    content = token * 40  # no punctuation/newlines, but many spaces

    chunks = chunk_text(content, "tokens.txt")

    assert len(chunks) >= 2
    first = chunks[0]["content"]
    second = chunks[1]["content"]

    assert first[-1].isspace() is False  # stripped
    assert not first.endswith("supercalifragilisticexpialidocious su"), first[-40:]
    assert second.startswith("supercalifragilisticexpialidocious"), second[:40]
