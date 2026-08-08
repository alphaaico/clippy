from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Optional

class Word(BaseModel):
    word: str
    start: float
    end: float

class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    words: list[Word] = []

class ClipScores(BaseModel):
    importance: int = Field(ge=1, le=10)
    hook: int = Field(ge=1, le=10)
    standalone: int = Field(ge=1, le=10)
    information_value: int = Field(ge=1, le=10)
    completeness: int = Field(ge=1, le=10)

class ClipCandidate(BaseModel):
    id: str
    title: str
    start: float
    end: float
    reason: str
    excerpt: str
    scores: ClipScores
    overall_score: int

class VideoProject(BaseModel):
    id: str
    status: str
    stage: str
    media: dict[str, Any] = {}
    transcript: list[TranscriptSegment] = []
    analysis: dict[str, Any] = {}
    clip_candidates: list[ClipCandidate] = []
    error: Optional[str] = None
