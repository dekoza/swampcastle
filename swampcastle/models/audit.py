"""Audit-overlay Pydantic models for MCP and read-only services."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .derived import CatalogCard
from .origin import SourceOrigin


class OriginLookupQuery(BaseModel):
    origin_id: str | None = None
    source_file: str | None = None

    @model_validator(mode="after")
    def validate_lookup_fields(self):
        if bool(self.origin_id) == bool(self.source_file):
            raise ValueError("Provide exactly one of origin_id or source_file")
        return self


class OriginLookupResponse(BaseModel):
    found: bool
    resolved_by: Literal["origin_id", "source_file"] | None = None
    path: str | None = None
    origin: SourceOrigin | None = None
    error: str | None = None


class CurationQuery(BaseModel):
    wing: str | None = None


class PersonaAliasData(BaseModel):
    canonical: str | None = None
    type: str = "agent_persona"


class NamedAliasData(BaseModel):
    canonical: str


class AliasCurationData(BaseModel):
    personas: dict[str, PersonaAliasData] = Field(default_factory=dict)
    people: dict[str, NamedAliasData] = Field(default_factory=dict)
    projects: dict[str, NamedAliasData] = Field(default_factory=dict)
    wing_hints: dict[str, str] = Field(default_factory=dict)


class TunnelRuleData(BaseModel):
    wing_a: str
    wing_b: str
    room: str
    weight: float = 0.0


class TunnelCurationData(BaseModel):
    allow: list[TunnelRuleData] = Field(default_factory=list)
    deny: list[TunnelRuleData] = Field(default_factory=list)
    boost: list[TunnelRuleData] = Field(default_factory=list)


class WingNoteData(BaseModel):
    wing: str
    path: str
    sections: dict[str, list[str]] = Field(default_factory=dict)


class CurationResponse(BaseModel):
    aliases: AliasCurationData = Field(default_factory=AliasCurationData)
    tunnels: TunnelCurationData = Field(default_factory=TunnelCurationData)
    available_wing_notes: list[str] = Field(default_factory=list)
    wing_note: WingNoteData | None = None
    error: str | None = None


class CatalogCardsQuery(BaseModel):
    wing: str


class CatalogCardsResponse(BaseModel):
    wing: str
    cards: list[CatalogCard] = Field(default_factory=list)
    path: str | None = None
    error: str | None = None
