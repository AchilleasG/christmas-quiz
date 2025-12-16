from typing import List, Optional

from pydantic import BaseModel, Field


class QuestionCreate(BaseModel):
    text: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    audio: List[str] = Field(default_factory=list)
    answer_type: str
    options: List[str] = Field(default_factory=list)
    duration_seconds: int = 30


class QuizCreate(BaseModel):
    name: str
    description: Optional[str] = None
    default_question_duration: int = 30
    gap_seconds: int = 3
    questions: List[QuestionCreate] = Field(default_factory=list)


class QuestionRead(BaseModel):
    id: str
    text: Optional[str]
    images: List[str]
    audio: List[str]
    answer_type: str
    options: List[str]
    duration_seconds: int


class QuizRead(BaseModel):
    id: str
    name: str
    description: Optional[str]
    default_question_duration: int
    gap_seconds: int
    questions: List[QuestionRead] = Field(default_factory=list)


class SessionCreate(BaseModel):
    name: str
    quiz_ids: List[str] = Field(default_factory=list)


class SessionRead(BaseModel):
    id: str
    name: str
    status: str
    auto_advance: bool
    manual_override: bool
    active_quiz_index: Optional[int]
    active_question_index: Optional[int]
