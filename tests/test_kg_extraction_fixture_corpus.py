"""Fixture-corpus test for KG extraction quality.

This is the first extraction quality gate: a small labeled corpus that measures
whether the current rule-based extractor still hits the expected narrow pattern
set without introducing obvious false positives.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from swampcastle.mining.extractors import extract_candidate_triples_from_text

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "kg_extraction" / "cases.yaml"


def _key(candidate) -> tuple[str, str, str, str]:
    return (
        candidate.subject_text,
        candidate.predicate,
        candidate.object_text,
        candidate.modality,
    )


def test_fixture_corpus_precision_and_recall():
    data = yaml.safe_load(_FIXTURE_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]

    total_expected = 0
    total_predicted = 0
    total_matched = 0
    case_failures = []

    for case in cases:
        candidates = extract_candidate_triples_from_text(
            case["text"],
            source_meta=case["source_meta"],
            extractor_version="rules-v1",
        )
        predicted = {_key(candidate) for candidate in candidates}
        expected = {
            (
                row["subject_text"],
                row["predicate"],
                row["object_text"],
                row["modality"],
            )
            for row in case.get("expected", [])
        }
        forbidden = {
            (
                row["subject_text"],
                row["predicate"],
                row["object_text"],
                row.get("modality", "asserted"),
            )
            for row in case.get("forbidden", [])
        }

        matched = predicted & expected
        missing = expected - predicted
        forbidden_hits = predicted & forbidden

        total_expected += len(expected)
        total_predicted += len(predicted)
        total_matched += len(matched)

        if missing or forbidden_hits:
            case_failures.append(
                {
                    "name": case["name"],
                    "missing": sorted(missing),
                    "forbidden_hits": sorted(forbidden_hits),
                    "predicted": sorted(predicted),
                }
            )

    precision = total_matched / total_predicted if total_predicted else 1.0
    recall = total_matched / total_expected if total_expected else 1.0

    assert not case_failures, f"Extractor fixture failures: {case_failures}"
    assert precision >= 0.95, f"Precision too low: {precision:.3f}"
    assert recall >= 0.95, f"Recall too low: {recall:.3f}"
