import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class SessionPlayer(SQLModel, table=True):
    __tablename__ = "session_players"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="sessions.id")
    name: str
    score: float = Field(default=0.0, ge=0)
    connected: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=True)))


class SessionAnswer(SQLModel, table=True):
    __tablename__ = "session_answers"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="sessions.id")
    question_id: str
    player_id: str = Field(foreign_key="session_players.id")
    answer: Optional[str] = None
    is_correct: bool = Field(default=False)
    submitted_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=True)))


class SessionSnapshot(SQLModel, table=True):
    __tablename__ = "session_snapshots"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="sessions.id")
    current_index: int
    current_entry_kind: Optional[str] = None
    quiz_id: Optional[str] = None
    question_id: Optional[str] = None
    active_quiz_index: Optional[int] = None
    active_question_index: Optional[int] = None
    current_start: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    current_end: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=True)))
