"""Source-origin models for audit metadata."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceOrigin(BaseModel):
    schema_version: int = 1
    origin_id: str
    source_kind: Literal["project_file", "conversation_export", "mixed", "unknown"]
    platform: str | None = None
    user_name: str | None = None
    agent_personas: list[str] = Field(default_factory=list)
    declared_transformations: list[str] = Field(default_factory=list)
    confidence: Literal["heuristic", "curated"] = "heuristic"
    source_file: str | None = None
    updated_at: str
