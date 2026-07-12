"""Catalog Pydantic models — status, wings, rooms, taxonomy."""

from typing import Optional

from pydantic import BaseModel


class StatusInput(BaseModel):
    project_dir: Optional[str] = None


class StatusDigest(BaseModel):
    """Rendered session digest — the `status` tool's payload (#24)."""

    digest: str
    castle_path: str
    error: Optional[str] = None
    partial: bool = False


class WingsResponse(BaseModel):
    wings: dict[str, int]
    error: Optional[str] = None


class RoomsResponse(BaseModel):
    wing: str
    rooms: dict[str, int]
    error: Optional[str] = None


class TaxonomyResponse(BaseModel):
    taxonomy: dict[str, dict[str, int]]
    error: Optional[str] = None


class WingBriefResponse(BaseModel):
    wing: str
    total_drawers: int
    rooms: dict[str, int]
    contributors: dict[str, int]
    source_files: int
    error: Optional[str] = None
