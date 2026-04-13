"""Drawer-related Pydantic models — search, add, delete, duplicate check."""

import hashlib
import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

MAX_NAME_LENGTH = 128
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_ .'\-]{0,126}[a-zA-Z0-9]?$")


def _validate_name(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    value = value.strip()
    if len(value) > MAX_NAME_LENGTH:
        raise ValueError(f"{field_name} exceeds {MAX_NAME_LENGTH} characters")
    if ".." in value or "/" in value or "\\" in value:
        raise ValueError(f"{field_name} contains invalid path characters")
    if "\x00" in value:
        raise ValueError(f"{field_name} contains null bytes")
    if not _SAFE_NAME_RE.match(value):
        raise ValueError(f"{field_name} contains invalid characters")
    return value


class SearchQuery(BaseModel):
    query: str = Field(max_length=500, description="Search keywords or question")
    limit: int = Field(default=5, ge=1, le=100)
    wing: Optional[str] = Field(default=None, description="Filter by wing")
    room: Optional[str] = Field(default=None, description="Filter by room")
    contributor: Optional[str] = Field(default=None, description="Filter by contributor")
    context: Optional[str] = Field(default=None, description="Background context, not embedded")


class SearchHit(BaseModel):
    text: str
    wing: str
    room: str
    similarity: float
    source_file: Optional[str] = None
    contributor: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit]
    filters: dict[str, Optional[str]] = {}
    query_sanitized: bool = False
    sanitizer: Optional[dict] = None


class AddDrawerCommand(BaseModel):
    wing: str
    room: str
    content: str = Field(max_length=100_000)
    source_file: Optional[str] = None
    added_by: str = "mcp"

    @field_validator("wing")
    @classmethod
    def validate_wing(cls, v):
        return _validate_name(v, "wing")

    @field_validator("room")
    @classmethod
    def validate_room(cls, v):
        return _validate_name(v, "room")

    @field_validator("content")
    @classmethod
    def validate_content(cls, v):
        if not v or not v.strip():
            raise ValueError("content must be a non-empty string")
        if "\x00" in v:
            raise ValueError("content contains null bytes")
        return v

    def drawer_id(self) -> str:
        hash_input = (self.wing + self.room + self.content[:100]).encode()
        return f"drawer_{self.wing}_{self.room}_{hashlib.sha256(hash_input).hexdigest()[:24]}"


class DrawerResult(BaseModel):
    success: bool
    drawer_id: Optional[str] = None
    wing: Optional[str] = None
    room: Optional[str] = None
    reason: Optional[str] = None
    error: Optional[str] = None


class DeleteDrawerCommand(BaseModel):
    drawer_id: str


class DeleteDrawerResult(BaseModel):
    success: bool
    drawer_id: str
    error: Optional[str] = None


class DuplicateCheckQuery(BaseModel):
    content: str
    threshold: float = Field(default=0.9, ge=0.0, le=1.0)


class DuplicateCheckResult(BaseModel):
    is_duplicate: bool
    matches: list[dict] = []
