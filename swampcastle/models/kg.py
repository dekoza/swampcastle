"""Knowledge graph Pydantic models."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class KGQueryParams(BaseModel):
    entity: str
    as_of: Optional[str] = None
    direction: str = Field(default="both", pattern="^(outgoing|incoming|both)$")


class KGQueryResult(BaseModel):
    entity: str
    as_of: Optional[str] = None
    facts: list[dict[str, Any]]
    count: int


class AddTripleCommand(BaseModel):
    subject: str
    predicate: str
    object: str
    valid_from: Optional[str] = None
    source_closet: Optional[str] = None


class TripleResult(BaseModel):
    success: bool
    triple_id: Optional[str] = None
    fact: Optional[str] = None
    error: Optional[str] = None


class InvalidateCommand(BaseModel):
    subject: str
    predicate: str
    object: str
    ended: Optional[str] = None


class InvalidateResult(BaseModel):
    success: bool
    fact: str
    ended: str


class TimelineQuery(BaseModel):
    entity: Optional[str] = None


class TimelineResult(BaseModel):
    entity: str
    timeline: list[dict[str, Any]]
    count: int


class KGStatsResult(BaseModel):
    entities: int
    triples: int
    current_facts: int
    expired_facts: int
    relationship_types: list[str]
