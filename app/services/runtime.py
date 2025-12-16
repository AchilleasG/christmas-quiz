import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utc_now
from app.models import Question, Quiz, Session, SessionQuiz
from app.models.session import SessionStatus


class RuntimeController:
    """Controls the running session timeline (single active session)."""

    def __init__(self):
        self.active_session_id: Optional[str] = None
        self.timeline: List[dict] = []
        self.current_index: int = -1
        self.current_entry: Optional[dict] = None
        self.current_start: Optional[datetime] = None
        self.current_end: Optional[datetime] = None
        self.timer_task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()

    async def start(self, session_id: str):
        async with self.lock:
            from app.db import get_session

            async with get_session() as db:
                session = await db.get(Session, session_id)
                if not session:
                    raise HTTPException(status_code=404, detail="Session not found")
                self.timeline = await self._build_timeline(session_id, db)
                if not self.timeline:
                    raise HTTPException(status_code=400, detail="Session has no questions to run")

                self.active_session_id = session_id
                self.current_index = -1
                session.status = SessionStatus.LIVE
                session.started_at = utc_now()
                await db.commit()
                await db.refresh(session)
                await self._advance(db, session)

    async def force_next(self, session_id: str):
        async with self.lock:
            if self.active_session_id != session_id:
                raise HTTPException(status_code=400, detail="Session is not active")
            from app.db import get_session

            async with get_session() as db:
                session = await db.get(Session, session_id)
                if not session:
                    raise HTTPException(status_code=404, detail="Session not found")
                await self._advance(db, session)

    async def _advance(self, db: AsyncSession, session: Session):
        self.current_index += 1
        if self.current_index >= len(self.timeline):
            session.status = SessionStatus.FINISHED
            session.finished_at = utc_now()
            session.active_quiz_index = None
            session.active_question_index = None
            await db.commit()
            self.active_session_id = None
            if self.timer_task:
                self.timer_task.cancel()
                self.timer_task = None
            return

        entry = self.timeline[self.current_index]
        session.active_quiz_index = entry["quiz_index"]
        session.active_question_index = entry["question_index"]
        await db.commit()
        self.current_entry = entry
        self.current_start = utc_now()
        self.current_end = self.current_start + timedelta(seconds=entry["duration_seconds"])
        await self._start_timer(session, entry["duration_seconds"], entry["gap_seconds"])

    async def _start_timer(self, session: Session, duration: int, gap: int):
        if self.timer_task:
            self.timer_task.cancel()

        async def timer_loop():
            await asyncio.sleep(duration)
            from app.db import get_session

            async with get_session() as inner_db:
                fresh = await inner_db.get(Session, session.id)
                if fresh and fresh.manual_override:
                    return
            await asyncio.sleep(gap)
            await self.force_next(session.id)

        self.timer_task = asyncio.create_task(timer_loop())

    async def set_manual(self, session_id: str, manual: bool):
        async with self.lock:
            from app.db import get_session

            async with get_session() as db:
                session = await db.get(Session, session_id)
                if not session:
                    raise HTTPException(status_code=404, detail="Session not found")
                session.manual_override = manual
                await db.commit()

            if not manual and self.active_session_id == session_id and self.current_entry:
                remaining = self.remaining_seconds()
                if remaining <= 0:
                    await self.force_next(session_id)
                else:
                    await self._start_timer(session, remaining, self.current_entry["gap_seconds"])

    def remaining_seconds(self) -> int:
        if not self.current_end or not self.current_start:
            return 0
        return max(0, int((self.current_end - utc_now()).total_seconds()))

    async def cancel(self, session_id: str):
        """Stop timers if this session is active (used on reset/delete)."""
        if self.active_session_id != session_id:
            return
        self.active_session_id = None
        self.timeline = []
        self.current_index = -1
        self.current_entry = None
        self.current_start = None
        self.current_end = None
        if self.timer_task:
            self.timer_task.cancel()
            self.timer_task = None

    async def state(self, session_id: str) -> dict:
        from app.db import get_session

        async with get_session() as db:
            session = await db.get(Session, session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            question_payload = None
            if self.current_entry and session.status == SessionStatus.LIVE:
                q: Question = self.current_entry["question"]
                question_payload = {
                    "quiz_index": self.current_entry["quiz_index"],
                    "question_index": self.current_entry["question_index"],
                    "text": q.text,
                    "images": q.images,
                    "audio": q.audio,
                    "answer_type": q.answer_type,
                    "options": q.options,
                    "duration_seconds": q.duration_seconds,
                    "started_at": self.current_start.isoformat() if self.current_start else None,
                    "closes_at": self.current_end.isoformat() if self.current_end else None,
                    "remaining_seconds": self.remaining_seconds(),
                }

            return {
                "id": session.id,
                "name": session.name,
                "status": session.status,
                "manual_override": session.manual_override,
                "active_quiz_index": session.active_quiz_index,
                "active_question_index": session.active_question_index,
                "question": question_payload,
            }

    async def _build_timeline(self, session_id: str, db: AsyncSession) -> List[dict]:
        result = await db.execute(
            select(SessionQuiz)
            .options(selectinload(SessionQuiz.quiz).selectinload(Quiz.questions))
            .where(SessionQuiz.session_id == session_id)
            .order_by(SessionQuiz.position)
        )
        entries: List[dict] = []
        quizzes = result.scalars().unique().all()
        for quiz_idx, link in enumerate(quizzes):
            if not link.quiz:
                continue
            ordered_questions = sorted(link.quiz.questions, key=lambda q: q.position)
            for question_idx, question in enumerate(ordered_questions):
                entries.append(
                    {
                        "quiz_index": quiz_idx,
                        "question_index": question_idx,
                        "duration_seconds": question.duration_seconds,
                        "gap_seconds": link.quiz.gap_seconds,
                        "question": question,
                    }
                )
        return entries


runtime = RuntimeController()
