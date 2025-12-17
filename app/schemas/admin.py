from typing import List, Optional

from pydantic import BaseModel, Field


class QuestionCreate(BaseModel):
    text: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    audio: List[str] = Field(default_factory=list)
    answer_type: str
    options: List[str] = Field(default_factory=list)
    correct_answer: Optional[str] = None
    scoring_type: str = Field(default="exact")
    duration_seconds: int = 30
    speed_bonus: bool = False


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
    correct_answer: Optional[str]
    scoring_type: str
    duration_seconds: int
    speed_bonus: bool
    position: int


class QuizRead(BaseModel):
    id: str
    name: str
    description: Optional[str]
    default_question_duration: int
    gap_seconds: int
    questions: List[QuestionRead] = Field(default_factory=list)


class QuestionUpdate(BaseModel):
    text: Optional[str] = None
    images: Optional[List[str]] = None
    audio: Optional[List[str]] = None
    answer_type: Optional[str] = None
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    scoring_type: Optional[str] = None
    duration_seconds: Optional[int] = None
    speed_bonus: Optional[bool] = None


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
