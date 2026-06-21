"""Sync Pydantic models."""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel


class SyncRecord(BaseModel):
    id: str
    document: str
    metadata: dict[str, Any]
    embedding: Optional[list[float]] = None

    def to_dict(self) -> dict:
        d = {"id": self.id, "document": self.document, "metadata": self.metadata}
        if self.embedding is not None:
            d["embedding"] = self.embedding
        return d

    @classmethod
    def from_dict(cls, d: dict) -> SyncRecord:
        return cls(
            id=d["id"],
            document=d["document"],
            metadata=d["metadata"],
            embedding=d.get("embedding"),
        )


class VersionVector(BaseModel):
    vector: dict[str, int] = {}

    def get(self, node_id: str) -> int:
        return self.vector.get(node_id, 0)

    def update(self, node_id: str, seq: int):
        if seq > self.vector.get(node_id, 0):
            self.vector[node_id] = seq

    def update_from_records(self, records: list[SyncRecord]):
        """Advance the vector from a batch of records."""
        for r in records:
            nid = r.metadata.get("node_id", "")
            s = r.metadata.get("seq", 0)
            if isinstance(s, str):
                s = int(s)
            if nid and s > self.vector.get(nid, 0):
                self.vector[nid] = s

    def to_dict(self) -> dict[str, int]:
        return dict(self.vector)

    @classmethod
    def from_dict(cls, d: dict) -> VersionVector:
        return cls(vector={k: int(v) for k, v in d.items()})


class VersionVectorStore:
    """File-backed persistence for VersionVector."""

    def __init__(self, path: str | None = None):
        self._path = path
        self._vv = self._load()

    def _load(self) -> VersionVector:
        if self._path:
            try:
                with open(self._path, "r") as f:
                    data = json.load(f)
                return VersionVector.from_dict(data)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        return VersionVector()

    def save(self) -> None:
        if self._path:
            with open(self._path, "w") as f:
                json.dump(self._vv.to_dict(), f)

    @property
    def vv(self) -> VersionVector:
        return self._vv

    def get(self, node_id: str) -> int:
        return self._vv.get(node_id)

    def update(self, node_id: str, seq: int):
        self._vv.update(node_id, seq)

    def update_from_records(self, records: list[SyncRecord]) -> None:
        before = dict(self._vv.vector)
        self._vv.update_from_records(records)
        if self._vv.vector != before:
            self.save()

    def to_dict(self) -> dict[str, int]:
        return self._vv.to_dict()


class ChangeSet(BaseModel):
    source_node: str
    records: list[SyncRecord] = []

    def to_dict(self) -> dict:
        return {
            "source_node": self.source_node,
            "records": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, d: dict) -> ChangeSet:
        return cls(
            source_node=d["source_node"],
            records=[SyncRecord.from_dict(r) for r in d.get("records", [])],
        )


class MergeResult(BaseModel):
    accepted: int = 0
    rejected_conflicts: int = 0
    errors: list[str] = []
    winning_records: list[SyncRecord] = []


class SyncStatus(BaseModel):
    node_id: str
    version_vector: dict[str, int]
    total_drawers: int
