"""Candidate-triple models for proposal-first KG extraction."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ALLOWED_KG_PREDICATES = {
    "uses",
    "depends_on",
    "migrated_from",
    "migrated_to",
    "deployed_to",
    "blocked_by",
    "fixed_by",
    "owned_by",
    "works_on",
    "maintains",
    "prefers",
    "decided",
    "reported",
    "requested",
    "replaced_by",
    "superseded_by",
}


class CandidateTriple(BaseModel):
    candidate_id: str
    subject_text: str
    predicate: str
    object_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    modality: Literal["asserted", "planned", "hypothetical", "question"]
    polarity: Literal["positive", "negative"]
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    evidence_drawer_id: str
    evidence_text: str
    source_file: Optional[str] = None
    wing: Optional[str] = None
    room: Optional[str] = None
    status: Literal["proposed", "accepted", "rejected"] = "proposed"
    extractor_version: str
    created_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    conflicts_with: list[str] = Field(default_factory=list)

    @field_validator("predicate")
    @classmethod
    def validate_predicate(cls, value: str) -> str:
        if value not in ALLOWED_KG_PREDICATES:
            raise ValueError(
                f"predicate must be one of: {', '.join(sorted(ALLOWED_KG_PREDICATES))}"
            )
        return value

    @field_validator("subject_text", "object_text", "evidence_text")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("text fields must be non-empty")
        return value.strip()


class CandidateTripleFilter(BaseModel):
    status: Literal["proposed", "accepted", "rejected"] | None = None
    predicate: str | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    wing: str | None = None
    room: str | None = None
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

    @field_validator("predicate")
    @classmethod
    def validate_optional_predicate(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in ALLOWED_KG_PREDICATES:
            raise ValueError(
                f"predicate must be one of: {', '.join(sorted(ALLOWED_KG_PREDICATES))}"
            )
        return value


class CandidateReviewCommand(BaseModel):
    candidate_id: str
    action: Literal["accept", "reject", "accept_and_invalidate_conflict"]
    subject_text: str | None = None
    predicate: str | None = None
    object_text: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None

    @field_validator("predicate")
    @classmethod
    def validate_optional_predicate(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in ALLOWED_KG_PREDICATES:
            raise ValueError(
                f"predicate must be one of: {', '.join(sorted(ALLOWED_KG_PREDICATES))}"
            )
        return value


class CandidateReviewResult(BaseModel):
    success: bool
    candidate_id: str
    status: Literal["accepted", "rejected"] | None = None
    triple_id: str | None = None
    subject_text: str | None = None
    predicate: str | None = None
    object_text: str | None = None
    invalidated_count: int = 0
    error: str | None = None
