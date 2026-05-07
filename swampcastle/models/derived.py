"""Pydantic models for derived audit artifacts."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .drawer import SearchQuery, SearchResponse


class CatalogCard(BaseModel):
    wing: str
    room: str
    topic: str
    entities: list[str] = Field(default_factory=list)
    drawer_ids: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)


class SearchTrace(BaseModel):
    schema_version: int = 1
    trace_id: str
    created_at: str
    request: SearchQuery
    response: SearchResponse
