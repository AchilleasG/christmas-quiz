import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy import Column, DateTime
from sqlmodel import Field, Relationship, SQLModel

# type checkers handled via strings to avoid circular imports
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.quiz import Quiz


class SessionStatus(str):
    DRAFT = "draft"
    LIVE = "live"
    FINISHED = "finished"


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    status: str = Field(default=SessionStatus.DRAFT)
    auto_advance: bool = Field(default=True)
    manual_override: bool = Field(default=False)
    active_quiz_index: Optional[int] = None
    active_question_index: Optional[int] = None
    started_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    finished_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    quizzes: list["SessionQuiz"] = Relationship(back_populates="session")


class SessionQuiz(SQLModel, table=True):
    __tablename__ = "session_quizzes"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="sessions.id")
    quiz_id: str = Field(foreign_key="quizzes.id")
    position: int = Field(sa_column=Column(Integer))

    session: Optional[Session] = Relationship(back_populates="quizzes")
    quiz: Optional["Quiz"] = Relationship()
