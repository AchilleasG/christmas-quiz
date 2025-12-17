import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.dependencies import get_db_session
from app.models import Question, Quiz, Session, SessionAnswer, SessionPlayer, SessionQuiz, SessionSnapshot
from app.models.session import SessionStatus
from app.schemas import (
    QuestionCreate,
    QuestionRead,
    QuestionUpdate,
    QuizCreate,
    QuizRead,
    SessionCreate,
    SessionRead,
)
from app.services.runtime import runtime
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/admin", tags=["admin"])


def serialize_question(question: Question) -> QuestionRead:
    return QuestionRead(
        id=question.id,
        text=question.text,
        images=question.images,
        audio=question.audio,
        answer_type=question.answer_type,
        options=question.options,
        correct_answer=question.correct_answer,
        scoring_type=question.scoring_type or "exact",
        duration_seconds=question.duration_seconds,
        position=question.position if question.position is not None else 0,
    )


def serialize_quiz(quiz: Quiz) -> QuizRead:
    ordered_questions = sorted(quiz.questions, key=lambda q: q.position or 0)
    return QuizRead(
        id=quiz.id,
        name=quiz.name,
        description=quiz.description,
        default_question_duration=quiz.default_question_duration,
        gap_seconds=quiz.gap_seconds,
        questions=[serialize_question(q) for q in ordered_questions],
    )


def validate_correct_answer(answer_type: str, options: list[str], correct_answer: str | None):
    if answer_type == "multiple_choice" and correct_answer and correct_answer not in options:
        raise HTTPException(status_code=400, detail="correct_answer must match one of the options for multiple choice")
    if answer_type == "numeric" and correct_answer:
        try:
            float(correct_answer)
        except ValueError:
            raise HTTPException(status_code=400, detail="correct_answer must be a number for numeric questions")


@router.post("/quizzes", response_model=QuizRead)
async def create_quiz(payload: QuizCreate, db: AsyncSession = Depends(get_db_session)):
    quiz = Quiz(
        name=payload.name,
        description=payload.description,
        default_question_duration=payload.default_question_duration,
        gap_seconds=payload.gap_seconds,
    )
    for idx, q in enumerate(payload.questions):
        duration = q.duration_seconds or payload.default_question_duration
        validate_correct_answer(q.answer_type, q.options, q.correct_answer)
        quiz.questions.append(
            Question(
                text=q.text,
                images=q.images,
                audio=q.audio,
                answer_type=q.answer_type,
                options=q.options,
                correct_answer=q.correct_answer,
                scoring_type=q.scoring_type or "exact",
                duration_seconds=duration,
                position=idx,
            )
        )
    db.add(quiz)
    await db.commit()
    await db.refresh(quiz, attribute_names=["questions"])
    return serialize_quiz(quiz)


@router.get("/quizzes", response_model=List[QuizRead])
async def list_quizzes(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Quiz).options(selectinload(Quiz.questions)))
    quizzes = result.scalars().unique().all()
    return [serialize_quiz(q) for q in quizzes]


@router.get("/quizzes/{quiz_id}", response_model=QuizRead)
async def get_quiz(quiz_id: str, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(
        select(Quiz)
        .options(selectinload(Quiz.questions))
        .where(Quiz.id == quiz_id)
    )
    quiz = result.scalars().first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return serialize_quiz(quiz)

@router.post("/quizzes/{quiz_id}/questions", response_model=QuizRead)
async def add_question(quiz_id: str, payload: QuestionCreate, db: AsyncSession = Depends(get_db_session)):
    quiz = await db.get(Quiz, quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    await db.refresh(quiz, attribute_names=["questions"])
    position = len(quiz.questions)
    validate_correct_answer(payload.answer_type, payload.options, payload.correct_answer)
    question = Question(
        quiz_id=quiz_id,
        text=payload.text,
        images=payload.images,
        audio=payload.audio,
        answer_type=payload.answer_type,
        options=payload.options,
        correct_answer=payload.correct_answer,
        scoring_type=payload.scoring_type or "exact",
        duration_seconds=payload.duration_seconds or quiz.default_question_duration,
        position=position,
    )
    db.add(question)
    await db.commit()
    await db.refresh(quiz, attribute_names=["questions"])
    return serialize_quiz(quiz)


@router.post("/quizzes/{quiz_id}/questions/reorder", response_model=QuizRead)
async def reorder_questions(quiz_id: str, order: List[str] = Body(...), db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Question).where(Question.quiz_id == quiz_id))
    questions = result.scalars().all()
    id_to_question = {q.id: q for q in questions}
    if set(order) != set(id_to_question.keys()):
        raise HTTPException(status_code=400, detail="Order list must include all question ids")
    for idx, qid in enumerate(order):
        id_to_question[qid].position = idx
    await db.commit()
    return await get_quiz(quiz_id, db)


@router.patch("/quizzes/{quiz_id}/questions/{question_id}", response_model=QuizRead)
async def update_question(
    quiz_id: str,
    question_id: str,
    payload: QuestionUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    question = await db.get(Question, question_id)
    if not question or question.quiz_id != quiz_id:
        raise HTTPException(status_code=404, detail="Question not found")

    for field in (
        "text",
        "images",
        "audio",
        "answer_type",
        "options",
        "correct_answer",
        "scoring_type",
        "duration_seconds",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(question, field, value)

    validate_correct_answer(question.answer_type, question.options, question.correct_answer)
    await db.commit()
    return await get_quiz(quiz_id, db)


@router.delete("/quizzes/{quiz_id}/questions/{question_id}", response_model=QuizRead)
async def delete_question(quiz_id: str, question_id: str, db: AsyncSession = Depends(get_db_session)):
    question = await db.get(Question, question_id)
    if not question or question.quiz_id != quiz_id:
        raise HTTPException(status_code=404, detail="Question not found")
    await db.delete(question)
    await db.commit()
    # Re-sequence remaining positions
    result = await db.execute(select(Question).where(Question.quiz_id == quiz_id).order_by(Question.position))
    for idx, q in enumerate(result.scalars().all()):
        q.position = idx
    await db.commit()
    return await get_quiz(quiz_id, db)


@router.post("/sessions", response_model=SessionRead)
async def create_session(payload: SessionCreate, db: AsyncSession = Depends(get_db_session)):
    if not payload.quiz_ids:
        raise HTTPException(status_code=400, detail="At least one quiz_id required")
    result = await db.exec(select(Quiz.id).where(Quiz.id.in_(payload.quiz_ids)))
    existing = {row[0] for row in result.all()}
    missing = set(payload.quiz_ids) - existing
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown quiz ids: {', '.join(missing)}")

    session = Session(name=payload.name)
    db.add(session)
    await db.flush()
    for idx, quiz_id in enumerate(payload.quiz_ids):
        db.add(SessionQuiz(session_id=session.id, quiz_id=quiz_id, position=idx))
    await db.commit()
    await db.refresh(session)
    return SessionRead(
        id=session.id,
        name=session.name,
        status=session.status,
        auto_advance=session.auto_advance,
        manual_override=session.manual_override,
        active_quiz_index=session.active_quiz_index,
        active_question_index=session.active_question_index,
    )


@router.get("/sessions/{session_id}/state")
async def session_state(session_id: str):
    return await runtime.state(session_id)


@router.get("/sessions")
async def list_sessions(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Session))
    return result.scalars().all()


@router.post("/sessions/{session_id}/reset", response_model=SessionRead)
async def reset_session(session_id: str, db: AsyncSession = Depends(get_db_session)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await runtime.cancel(session_id)
    session.status = SessionStatus.DRAFT
    session.manual_override = False
    session.active_quiz_index = None
    session.active_question_index = None
    session.started_at = None
    session.finished_at = None
    # Clear persisted answers/snapshots and reset player scores
    await db.execute(delete(SessionSnapshot).where(SessionSnapshot.session_id == session_id))
    await db.execute(delete(SessionAnswer).where(SessionAnswer.session_id == session_id))
    await db.execute(delete(SessionPlayer).where(SessionPlayer.session_id == session_id))
    await db.commit()
    await db.refresh(session)
    return SessionRead(
        id=session.id,
        name=session.name,
        status=session.status,
        auto_advance=session.auto_advance,
        manual_override=session.manual_override,
        active_quiz_index=session.active_quiz_index,
        active_question_index=session.active_question_index,
    )


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db_session)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await runtime.cancel(session_id)
    # Clean up related rows to avoid FK violations
    await db.execute(delete(SessionSnapshot).where(SessionSnapshot.session_id == session_id))
    await db.execute(delete(SessionAnswer).where(SessionAnswer.session_id == session_id))
    await db.execute(delete(SessionPlayer).where(SessionPlayer.session_id == session_id))
    await db.execute(delete(SessionQuiz).where(SessionQuiz.session_id == session_id))
    await db.delete(session)
    await db.commit()
    return {"deleted": session_id}


@router.post("/sessions/{session_id}/reveal_scores", response_model=SessionRead)
async def reveal_scores(session_id: str, reveal: bool = True, db: AsyncSession = Depends(get_db_session)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != SessionStatus.FINISHED:
        raise HTTPException(status_code=400, detail="Scores can only be revealed after the session is finished")
    await runtime.set_scores_revealed(session_id, reveal)
    await db.refresh(session)
    return SessionRead(
        id=session.id,
        name=session.name,
        status=session.status,
        auto_advance=session.auto_advance,
        manual_override=session.manual_override,
        active_quiz_index=session.active_quiz_index,
        active_question_index=session.active_question_index,
    )


@router.post("/sessions/{session_id}/duplicate", response_model=SessionRead)
async def duplicate_session(session_id: str, db: AsyncSession = Depends(get_db_session)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    links = await db.execute(select(SessionQuiz).where(SessionQuiz.session_id == session_id).order_by(SessionQuiz.position))
    quiz_ids = [link.quiz_id for link in links.scalars().all()]
    new_session = Session(name=f"{session.name} (copy)")
    db.add(new_session)
    await db.flush()
    for idx, qid in enumerate(quiz_ids):
        db.add(SessionQuiz(session_id=new_session.id, quiz_id=qid, position=idx))
    await db.commit()
    await db.refresh(new_session)
    return SessionRead(
        id=new_session.id,
        name=new_session.name,
        status=new_session.status,
        auto_advance=new_session.auto_advance,
        manual_override=new_session.manual_override,
        active_quiz_index=new_session.active_quiz_index,
        active_question_index=new_session.active_question_index,
    )


@router.post("/sessions/{session_id}/start", response_model=SessionRead)
async def start_session(session_id: str, db: AsyncSession = Depends(get_db_session)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await runtime.start(session_id)
    await db.refresh(session)
    return SessionRead(
        id=session.id,
        name=session.name,
        status=session.status,
        auto_advance=session.auto_advance,
        manual_override=session.manual_override,
        active_quiz_index=session.active_quiz_index,
        active_question_index=session.active_question_index,
    )


@router.post("/sessions/{session_id}/resume", response_model=SessionRead)
async def resume_session(session_id: str, db: AsyncSession = Depends(get_db_session)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await runtime.resume(session_id)
    await db.refresh(session)
    return SessionRead(
        id=session.id,
        name=session.name,
        status=session.status,
        auto_advance=session.auto_advance,
        manual_override=session.manual_override,
        active_quiz_index=session.active_quiz_index,
        active_question_index=session.active_question_index,
    )


@router.post("/sessions/{session_id}/manual", response_model=SessionRead)
async def toggle_manual(session_id: str, manual: bool, db: AsyncSession = Depends(get_db_session)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await runtime.set_manual(session_id, manual)
    await db.refresh(session)
    return SessionRead(
        id=session.id,
        name=session.name,
        status=session.status,
        auto_advance=session.auto_advance,
        manual_override=session.manual_override,
        active_quiz_index=session.active_quiz_index,
        active_question_index=session.active_question_index,
    )


@router.post("/sessions/{session_id}/next", response_model=SessionRead)
async def force_next(session_id: str, db: AsyncSession = Depends(get_db_session)):
    session = await db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await runtime.force_next(session_id)
    await db.refresh(session)
    return SessionRead(
        id=session.id,
        name=session.name,
        status=session.status,
        auto_advance=session.auto_advance,
        manual_override=session.manual_override,
        active_quiz_index=session.active_quiz_index,
        active_question_index=session.active_question_index,
    )


@router.post("/upload")
async def upload_media(
    kind: str = Form(..., regex="^(image|audio)$"),
    file: UploadFile = File(...),
):
    allowed_image = {"image/png", "image/jpeg", "image/jpg", "image/gif"}
    allowed_audio = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/x-wav"}
    if kind == "image" and file.content_type not in allowed_image:
        raise HTTPException(status_code=400, detail="Unsupported image type")
    if kind == "audio" and file.content_type not in allowed_audio:
        raise HTTPException(status_code=400, detail="Unsupported audio type")

    ext = Path(file.filename or "").suffix or (".jpg" if kind == "image" else ".mp3")
    filename = f"{uuid.uuid4()}{ext}"
    target_dir = settings.media_root / ("images" if kind == "image" else "audio")
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / filename

    data = await file.read()
    destination.write_bytes(data)

    url = f"/media/{'images' if kind == 'image' else 'audio'}/{filename}"
    return {"url": url, "filename": filename, "content_type": file.content_type}
