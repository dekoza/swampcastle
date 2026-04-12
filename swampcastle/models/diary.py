"""Diary Pydantic models."""

from typing import Optional

from pydantic import BaseModel, Field


class DiaryWriteCommand(BaseModel):
    agent_name: str
    entry: str = Field(max_length=100_000)
    topic: str = "general"


class DiaryEntry(BaseModel):
    date: str
    timestamp: str
    topic: str
    content: str


class DiaryResponse(BaseModel):
    agent: str
    entries: list[DiaryEntry]
    message: Optional[str] = None


class DiaryWriteResult(BaseModel):
    success: bool
    entry_id: Optional[str] = None
    agent: Optional[str] = None
    topic: Optional[str] = None
    timestamp: Optional[str] = None
    error: Optional[str] = None
