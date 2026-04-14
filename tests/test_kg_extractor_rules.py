"""Tests for rule-based KG proposal extraction."""

from swampcastle.mining.extractors import extract_candidate_triples_from_text


def _meta():
    return {
        "drawer_id": "drawer_1",
        "wing": "swampcastle",
        "room": "architecture",
        "source_file": "README.md",
    }


def test_migration_sentence_produces_from_and_to_candidates():
    text = "We switched from Auth0 to Clerk because local testing got simpler."
    candidates = extract_candidate_triples_from_text(
        text, source_meta=_meta(), extractor_version="rules-v1"
    )

    predicates = {(c.predicate, c.object_text) for c in candidates}
    assert ("migrated_from", "Auth0") in predicates
    assert ("migrated_to", "Clerk") in predicates
    assert all(c.subject_text == "swampcastle" for c in candidates)
    assert all(c.modality == "asserted" for c in candidates)


def test_explicit_person_ownership_pattern():
    text = "Kai works on Orion and maintains the deployment pipeline."
    candidates = extract_candidate_triples_from_text(
        text, source_meta=_meta(), extractor_version="rules-v1"
    )

    assert any(
        c.subject_text == "Kai" and c.predicate == "works_on" and c.object_text == "Orion"
        for c in candidates
    )


def test_usage_pattern_uses_wing_as_implicit_subject():
    text = "We use LanceDB for vector storage."
    candidates = extract_candidate_triples_from_text(
        text, source_meta=_meta(), extractor_version="rules-v1"
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.subject_text == "swampcastle"
    assert candidate.predicate == "uses"
    assert candidate.object_text == "LanceDB"


def test_hypothetical_statement_is_marked_non_asserted():
    text = "Maybe we should try Clerk someday."
    candidates = extract_candidate_triples_from_text(
        text, source_meta=_meta(), extractor_version="rules-v1"
    )

    assert len(candidates) == 1
    assert candidates[0].modality == "hypothetical"
    assert candidates[0].object_text == "Clerk"


def test_question_does_not_produce_candidates():
    text = "Should we switch from Auth0 to Clerk?"
    candidates = extract_candidate_triples_from_text(
        text, source_meta=_meta(), extractor_version="rules-v1"
    )
    assert candidates == []
