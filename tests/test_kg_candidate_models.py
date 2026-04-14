"""Tests for KG candidate-triple models."""

import pytest

from swampcastle.models import CandidateReviewCommand, CandidateTriple, CandidateTripleFilter


def test_candidate_triple_valid():
    candidate = CandidateTriple(
        candidate_id="cand_1",
        subject_text="SwampCastle",
        predicate="uses",
        object_text="LanceDB",
        confidence=0.82,
        modality="asserted",
        polarity="positive",
        valid_from="2026-01-01",
        evidence_drawer_id="drawer_1",
        evidence_text="SwampCastle uses LanceDB for vector storage.",
        source_file="README.md",
        wing="proj",
        room="storage",
        status="proposed",
        extractor_version="rules-v1",
    )
    assert candidate.predicate == "uses"
    assert candidate.status == "proposed"


def test_candidate_triple_rejects_unknown_predicate():
    with pytest.raises(Exception):
        CandidateTriple(
            candidate_id="cand_1",
            subject_text="SwampCastle",
            predicate="invented_relation",
            object_text="LanceDB",
            confidence=0.82,
            modality="asserted",
            polarity="positive",
            evidence_drawer_id="drawer_1",
            evidence_text="text",
            status="proposed",
            extractor_version="rules-v1",
        )


def test_candidate_review_command_valid_accept():
    cmd = CandidateReviewCommand(candidate_id="cand_1", action="accept", predicate="uses")
    assert cmd.action == "accept"
    assert cmd.predicate == "uses"


def test_candidate_review_command_rejects_unknown_predicate_override():
    with pytest.raises(Exception):
        CandidateReviewCommand(
            candidate_id="cand_1",
            action="accept",
            predicate="totally_new_predicate",
        )


def test_candidate_filter_defaults():
    f = CandidateTripleFilter()
    assert f.status is None
    assert f.limit == 50
    assert f.offset == 0
