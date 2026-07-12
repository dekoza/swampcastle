"""Checkpoint — the batched "file this session" write surface.

One MCP call semantic-dedups each item, files the non-duplicates as
drawers, and writes one diary entry (upstream MemPalace #1851). Items
reuse the drawer name validators so a malformed item fails the whole
call at validation time, before anything is filed.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from swampcastle.models.drawer import _validate_name


class CheckpointItem(BaseModel):
    wing: str
    room: str
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("wing")
    @classmethod
    def validate_wing(cls, v):
        return _validate_name(v, "wing")

    @field_validator("room")
    @classmethod
    def validate_room(cls, v):
        return _validate_name(v, "room")


class CheckpointDiary(BaseModel):
    agent_name: str
    entry: str = Field(min_length=1, max_length=100_000)
    topic: str = "session-checkpoint"


class CheckpointCommand(BaseModel):
    items: list[CheckpointItem] = Field(default_factory=list)
    diary: Optional[CheckpointDiary] = None
    dedup_threshold: float = Field(default=0.9, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_items_or_diary(self):
        if not self.items and self.diary is None:
            raise ValueError("checkpoint needs at least one item or a diary entry")
        return self


class CheckpointResult(BaseModel):
    added: list[dict[str, Any]] = Field(default_factory=list)
    duplicates: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    diary: Optional[dict[str, Any]] = None
