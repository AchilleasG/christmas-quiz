from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Player(BaseModel):
    id: str
    name: str
    connected: bool = False


class Question(BaseModel):
    id: str
    text: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    audio: List[str] = Field(default_factory=list)
    answer_type: str
    options: List[str] = Field(default_factory=list)
    duration_seconds: int = 30
    starts_at: Optional[datetime] = None
    closes_at: Optional[datetime] = None


class SessionSummary(BaseModel):
    id: str
    title: str
    player_count: int
    active_question_id: Optional[str]


class SessionState(BaseModel):
    id: str
    title: str
    players: List[Player]
    disconnected_players: List[Player]
    question: Optional[Question]
    now: datetime


class NewSessionRequest(BaseModel):
    title: str


class QuestionRequest(BaseModel):
    text: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    audio: List[str] = Field(default_factory=list)
    answer_type: str
    options: List[str] = Field(default_factory=list)
    duration_seconds: int = 30


class AnswerMessage(BaseModel):
    type: str
    player_id: str
    answer: Optional[str] = None


class JoinMessage(BaseModel):
    type: str
    name: Optional[str] = None
    player_id: Optional[str] = None

