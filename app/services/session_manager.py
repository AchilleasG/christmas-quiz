import asyncio
import uuid
from datetime import timedelta
from typing import Dict, List, Optional

from fastapi import HTTPException, WebSocket

from app.core.time import utc_now
from app.schemas import Player, Question, SessionState, SessionSummary


class SessionData:
    """In-memory holder for a single session's data and sockets."""

    def __init__(self, title: str):
        self.id = str(uuid.uuid4())[:8]
        self.title = title
        self.players: Dict[str, Player] = {}
        self.player_sockets: Dict[str, List[WebSocket]] = {}
        self.admin_sockets: List[WebSocket] = []
        self.current_question: Optional[Question] = None
        self.answers: Dict[str, str] = {}
        self.lock = asyncio.Lock()
        self.timer_task: Optional[asyncio.Task] = None

    def summary(self) -> SessionSummary:
        return SessionSummary(
            id=self.id,
            title=self.title,
            player_count=len(self.players),
            active_question_id=self.current_question.id if self.current_question else None,
        )

    def state(self) -> SessionState:
        disconnected = [p for p in self.players.values() if not p.connected]
        return SessionState(
            id=self.id,
            title=self.title,
            players=list(self.players.values()),
            disconnected_players=disconnected,
            question=self.current_question,
            now=utc_now(),
        )

    async def set_question(self, question: Question) -> None:
        async with self.lock:
            self.current_question = question
            self.answers.clear()
            self._start_timer()
            await self.broadcast_state()

    async def end_question(self) -> None:
        async with self.lock:
            self.current_question = None
            if self.timer_task:
                self.timer_task.cancel()
                self.timer_task = None
            await self.broadcast_state()

    def _start_timer(self) -> None:
        if self.timer_task:
            self.timer_task.cancel()
        self.timer_task = asyncio.create_task(self._timer_loop())

    async def _timer_loop(self):
        try:
            while self.current_question:
                now = utc_now()
                if self.current_question.closes_at and now >= self.current_question.closes_at:
                    break
                await self.broadcast_state()
                await asyncio.sleep(1)
        finally:
            async with self.lock:
                if self.current_question and self.current_question.closes_at:
                    self.current_question.closes_at = utc_now()
                await self.broadcast_state()

    async def broadcast_state(self):
        state = self.state().dict()
        await _broadcast(self.admin_sockets, {"type": "state", "state": state})
        await _broadcast(
            [ws for sockets in self.player_sockets.values() for ws in sockets],
            {"type": "state", "state": state},
        )


class SessionStore:
    """Manage lifecycle of quiz sessions."""

    def __init__(self):
        self.sessions: Dict[str, SessionData] = {}
        self.lock = asyncio.Lock()

    async def create_session(self, title: str) -> SessionData:
        session = SessionData(title=title)
        async with self.lock:
            self.sessions[session.id] = session
        return session

    def get(self, session_id: str) -> SessionData:
        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session


async def _broadcast(sockets: List[WebSocket], message: dict):
    to_remove = []
    for ws in sockets:
        try:
            await ws.send_json(message)
        except Exception:
            to_remove.append(ws)
    for ws in to_remove:
        sockets.remove(ws)


def build_question_from_request(payload) -> Question:
    """Helper to prepare question with ids/timestamps."""
    qid = str(uuid.uuid4())[:8]
    starts = utc_now()
    closes = starts + timedelta(seconds=payload.duration_seconds)
    return Question(
        id=qid,
        text=payload.text,
        images=payload.images,
        audio=payload.audio,
        answer_type=payload.answer_type,
        options=payload.options,
        duration_seconds=payload.duration_seconds,
        starts_at=starts,
        closes_at=closes,
    )

