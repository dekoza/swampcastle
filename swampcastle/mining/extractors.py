"""Rule-based candidate-triple extraction for KG proposals.

This is a narrow, precision-first extractor. It does not attempt open relation
extraction. It only emits proposals for a closed predicate vocabulary and
prefers explicit, high-signal patterns.
"""

from __future__ import annotations

import hashlib
import re

from swampcastle.models.kg_candidates import CandidateTriple

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_ENTITY_TOKEN = r"[A-Za-z][A-Za-z0-9_.-]*"
_SUBJECT_TOKEN = r"[A-Z][A-Za-z0-9_.-]*"

_HYPOTHETICAL_MARKERS = (
    "maybe",
    "might",
    "could",
    "should",
    "someday",
    "consider",
    "thinking about",
)
_PLANNED_MARKERS = (
    "plan to",
    "going to",
    "will ",
)

_MIGRATE_FROM_TO_PATTERNS = (
    re.compile(rf"\bswitched from\s+({_ENTITY_TOKEN})\s+to\s+({_ENTITY_TOKEN})\b", re.I),
    re.compile(rf"\bmigrated from\s+({_ENTITY_TOKEN})\s+to\s+({_ENTITY_TOKEN})\b", re.I),
)
_REPLACED_WITH_PATTERN = re.compile(
    rf"\breplaced\s+({_ENTITY_TOKEN})\s+with\s+({_ENTITY_TOKEN})\b", re.I
)
_USES_PATTERN = re.compile(rf"\b(?:we|it|system|project)\s+use\s+({_ENTITY_TOKEN})\b", re.I)
_DEPENDS_ON_PATTERN = re.compile(
    rf"\b(?:we|it|system|project)\s+depends on\s+({_ENTITY_TOKEN})\b", re.I
)
_BUILT_WITH_PATTERN = re.compile(
    rf"\b(?:we|it|system|project)\s+built with\s+({_ENTITY_TOKEN})\b", re.I
)
_DEPLOYED_TO_PATTERN = re.compile(
    rf"\b(?:we|it|system|project)\s+deployed to\s+({_ENTITY_TOKEN})\b", re.I
)
_EXPLICIT_SUBJECT_PATTERNS = (
    ("uses", re.compile(rf"\b({_SUBJECT_TOKEN})\s+uses\s+({_ENTITY_TOKEN})\b")),
    (
        "depends_on",
        re.compile(rf"\b({_SUBJECT_TOKEN})\s+depends on\s+({_ENTITY_TOKEN})\b", re.I),
    ),
    (
        "uses",
        re.compile(rf"\b({_SUBJECT_TOKEN})\s+built with\s+({_ENTITY_TOKEN})\b", re.I),
    ),
    (
        "deployed_to",
        re.compile(rf"\b({_SUBJECT_TOKEN})\s+deployed to\s+({_ENTITY_TOKEN})\b", re.I),
    ),
)
_WORKS_ON_PATTERN = re.compile(rf"\b({_SUBJECT_TOKEN})\s+works on\s+({_SUBJECT_TOKEN})\b")
_MAINTAINS_PATTERN = re.compile(rf"\b({_SUBJECT_TOKEN})\s+maintains\s+({_SUBJECT_TOKEN})\b")
_TRY_PATTERN = re.compile(rf"\b(?:try|use)\s+({_ENTITY_TOKEN})\b", re.I)


def _sentence_split(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part and part.strip()]


def _detect_modality(text: str) -> str:
    text_lower = text.lower()
    if "?" in text_lower:
        return "question"
    if any(marker in text_lower for marker in _HYPOTHETICAL_MARKERS):
        return "hypothetical"
    if any(marker in text_lower for marker in _PLANNED_MARKERS):
        return "planned"
    return "asserted"


def _implicit_subject(source_meta: dict) -> str:
    return source_meta.get("wing") or source_meta.get("source_file") or "project"


def _candidate_id(
    predicate: str, subject_text: str, object_text: str, evidence_drawer_id: str
) -> str:
    digest = hashlib.sha256(
        f"{predicate}\x00{subject_text}\x00{object_text}\x00{evidence_drawer_id}".encode()
    ).hexdigest()[:16]
    return f"preview_{digest}"


def _make_candidate(
    *,
    predicate: str,
    subject_text: str,
    object_text: str,
    confidence: float,
    modality: str,
    source_meta: dict,
    evidence_text: str,
    extractor_version: str,
) -> CandidateTriple:
    evidence_drawer_id = source_meta.get("drawer_id") or "unknown"
    return CandidateTriple(
        candidate_id=_candidate_id(predicate, subject_text, object_text, evidence_drawer_id),
        subject_text=subject_text,
        predicate=predicate,
        object_text=object_text,
        confidence=confidence,
        modality=modality,
        polarity="positive",
        valid_from=None,
        valid_to=None,
        evidence_drawer_id=evidence_drawer_id,
        evidence_text=evidence_text,
        source_file=source_meta.get("source_file"),
        wing=source_meta.get("wing"),
        room=source_meta.get("room"),
        status="proposed",
        extractor_version=extractor_version,
    )


def extract_candidate_triples_from_text(
    text: str,
    *,
    source_meta: dict,
    extractor_version: str,
) -> list[CandidateTriple]:
    candidates: list[CandidateTriple] = []

    for sentence in _sentence_split(text):
        modality = _detect_modality(sentence)
        if modality == "question":
            continue

        implicit_subject = _implicit_subject(source_meta)

        for pattern in _MIGRATE_FROM_TO_PATTERNS:
            match = pattern.search(sentence)
            if match:
                from_obj, to_obj = match.group(1), match.group(2)
                candidates.append(
                    _make_candidate(
                        predicate="migrated_from",
                        subject_text=implicit_subject,
                        object_text=from_obj,
                        confidence=0.9,
                        modality=modality,
                        source_meta=source_meta,
                        evidence_text=sentence,
                        extractor_version=extractor_version,
                    )
                )
                candidates.append(
                    _make_candidate(
                        predicate="migrated_to",
                        subject_text=implicit_subject,
                        object_text=to_obj,
                        confidence=0.9,
                        modality=modality,
                        source_meta=source_meta,
                        evidence_text=sentence,
                        extractor_version=extractor_version,
                    )
                )
                break

        match = _REPLACED_WITH_PATTERN.search(sentence)
        if match:
            old_obj, new_obj = match.group(1), match.group(2)
            candidates.append(
                _make_candidate(
                    predicate="migrated_from",
                    subject_text=implicit_subject,
                    object_text=old_obj,
                    confidence=0.88,
                    modality=modality,
                    source_meta=source_meta,
                    evidence_text=sentence,
                    extractor_version=extractor_version,
                )
            )
            candidates.append(
                _make_candidate(
                    predicate="migrated_to",
                    subject_text=implicit_subject,
                    object_text=new_obj,
                    confidence=0.88,
                    modality=modality,
                    source_meta=source_meta,
                    evidence_text=sentence,
                    extractor_version=extractor_version,
                )
            )

        for predicate, pattern in _EXPLICIT_SUBJECT_PATTERNS:
            match = pattern.search(sentence)
            if match:
                subject_text, object_text = match.group(1), match.group(2)
                if subject_text.lower() not in {"we", "it", "system", "project"}:
                    candidates.append(
                        _make_candidate(
                            predicate=predicate,
                            subject_text=subject_text,
                            object_text=object_text,
                            confidence=0.84 if modality == "asserted" else 0.58,
                            modality=modality,
                            source_meta=source_meta,
                            evidence_text=sentence,
                            extractor_version=extractor_version,
                        )
                    )

        for predicate, pattern, confidence in (
            ("uses", _USES_PATTERN, 0.8),
            ("depends_on", _DEPENDS_ON_PATTERN, 0.8),
            ("uses", _BUILT_WITH_PATTERN, 0.76),
            ("deployed_to", _DEPLOYED_TO_PATTERN, 0.82),
        ):
            match = pattern.search(sentence)
            if match:
                candidates.append(
                    _make_candidate(
                        predicate=predicate,
                        subject_text=implicit_subject,
                        object_text=match.group(1),
                        confidence=confidence if modality == "asserted" else 0.58,
                        modality=modality,
                        source_meta=source_meta,
                        evidence_text=sentence,
                        extractor_version=extractor_version,
                    )
                )

        for predicate, pattern, confidence in (
            ("works_on", _WORKS_ON_PATTERN, 0.84),
            ("maintains", _MAINTAINS_PATTERN, 0.82),
        ):
            match = pattern.search(sentence)
            if match:
                candidates.append(
                    _make_candidate(
                        predicate=predicate,
                        subject_text=match.group(1),
                        object_text=match.group(2),
                        confidence=confidence if modality == "asserted" else 0.58,
                        modality=modality,
                        source_meta=source_meta,
                        evidence_text=sentence,
                        extractor_version=extractor_version,
                    )
                )

        if modality == "hypothetical":
            match = _TRY_PATTERN.search(sentence)
            if match:
                candidates.append(
                    _make_candidate(
                        predicate="uses",
                        subject_text=implicit_subject,
                        object_text=match.group(1),
                        confidence=0.55,
                        modality=modality,
                        source_meta=source_meta,
                        evidence_text=sentence,
                        extractor_version=extractor_version,
                    )
                )

    # De-duplicate within one drawer preview by candidate_id
    deduped: dict[str, CandidateTriple] = {}
    for candidate in candidates:
        deduped[candidate.candidate_id] = candidate
    return list(deduped.values())
