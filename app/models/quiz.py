import uuid
from typing import List, Optional

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel


class Quiz(SQLModel, table=True):
    __tablename__ = "quizzes"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    description: Optional[str] = None
    default_question_duration: int = Field(default=30, ge=5)
    gap_seconds: int = Field(default=3, ge=0)

    questions: List["Question"] = Relationship(
        back_populates="quiz",
        sa_relationship_kwargs={"order_by": "Question.position"},
    )


class Question(SQLModel, table=True):
    __tablename__ = "questions"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    quiz_id: str = Field(foreign_key="quizzes.id")
    text: Optional[str] = None
    images: list[str] = Field(sa_column=Column(JSONB, default=list))
    audio: list[str] = Field(sa_column=Column(JSONB, default=list))
    answer_type: str
    options: list[str] = Field(sa_column=Column(JSONB, default=list))
    correct_answer: Optional[str] = None
    scoring_type: str = Field(default="exact")
    speed_bonus: bool = Field(default=False)
    duration_seconds: int = Field(default=30, ge=5)
    position: int = Field(sa_column=Column(Integer), default=0)

    quiz: Optional[Quiz] = Relationship(back_populates="questions")
