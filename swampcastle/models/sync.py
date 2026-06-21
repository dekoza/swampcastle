"""Sync Pydantic models."""

from typing import Any, Optional

from pydantic import BaseModel


class SyncRecord(BaseModel):
    id: str
    document: str
    metadata: dict[str, Any]
    embedding: Optional[list[float]] = None


class VersionVector(BaseModel):
    vector: dict[str, int] = {}

    def get(self, node_id: str) -> int:
        return self.vector.get(node_id, 0)

    def update(self, node_id: str, seq: int):
        if seq > self.vector.get(node_id, 0):
            self.vector[node_id] = seq


class ChangeSet(BaseModel):
    source_node: str
    records: list[SyncRecord] = []
    version_vector: VersionVector = VersionVector()


class MergeResult(BaseModel):
    accepted: int = 0
    rejected_conflicts: int = 0
    errors: list[str] = []


class SyncStatus(BaseModel):
    node_id: str
    version_vector: dict[str, int]
    total_drawers: int
