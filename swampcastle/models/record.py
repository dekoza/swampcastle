"""Typed record models for SwampCastle's memory domain.

These are generic memory-system primitives, not Patsy-specific.
Consumers place domain-specific fields in the metadata dict.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

RecordKind = Literal[
    "document",
    "transcript",
    "curation",
    "tombstone",
    "manifest",
    "control",
]


class RecordEnvelope(BaseModel):
    """A typed canonical record stored in a SwampCastle collection.

    This is the generic envelope. SwampCastle treats the ``kind`` as a
    first-class indexed field; everything else lives in ``metadata``
    and is opaque to the storage layer.
    """

    record_id: str = Field(min_length=1)
    kind: RecordKind
    node_id: str = Field(default="")
    seq: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["RecordEnvelope", "RecordKind"]
