"""Vault service models — GCCollectResult, DiaryReadQuery."""

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass
class GCCollectResult:
    deleted_ids: list[str]


class DiaryReadQuery(BaseModel):
    agent_name: str
    last_n: int = Field(default=10, ge=1, le=1000)
