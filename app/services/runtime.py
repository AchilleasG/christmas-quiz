import asyncio
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utc_now
from app.models import Question, Quiz, Session, SessionAnswer, SessionPlayer, SessionQuiz, SessionSnapshot
from app.models.session import SessionStatus
from app.services.ai_evaluator import evaluate_text_answer


class RuntimeController:
    """Controls the running session timeline (single active session)."""

    def __init__(self):
        self.logger = logging.getLogger("runtime")
        self.active_session_id: Optional[str] = None
        self.timeline: List[dict] = []
        self.current_index: int = -1
        self.current_entry: Optional[dict] = None
        self.current_start: Optional[datetime] = None
        self.current_end: Optional[datetime] = None
        self.current_finalized: bool = False
        self.timer_task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()
        # Player state per session_id
        self.players: dict[str, dict[str, dict]] = {}
        self.player_sockets: dict[str, list] = {}
        # Track answers submitted for current question by session_id -> set of player_ids
        self.answers: dict[str, set[str]] = {}
        # Track if scores are revealed at end
        self.scores_revealed: dict[str, bool] = {}
        # Track correctness per player for current question
        self.answer_results: dict[str, dict[str, Optional[bool]]] = {}
        # Track raw answers per player for current question (used for numeric reveal list)
        self.answer_values: dict[str, dict[str, Optional[str]]] = {}
        # Track closest question rankings
        self.closest_results: dict[str, list] = {}

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
                self.scores_revealed[session_id] = False
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
        # Finalize scoring for the question we are leaving
        if self.current_entry and self.current_entry.get("kind") == "question":
            if not self.current_finalized:
                await self._finalize_question_scores(session.id, self.current_entry["question"])

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
            await self.broadcast_state(session.id)
            return

        entry = self.timeline[self.current_index]
        session.active_quiz_index = entry["quiz_index"]
        session.active_question_index = entry.get("question_index")
        await db.commit()
        self.current_entry = entry
        self.current_start = utc_now()
        self.current_end = (
            self.current_start + timedelta(seconds=entry["duration_seconds"])
            if entry["kind"] == "question"
            else None
        )
        self.current_finalized = False
        # New question should clear answer tracking
        if entry["kind"] == "question":
            self.answers[session.id] = set()
            self.answer_results[session.id] = {}
            self.answer_values[session.id] = {}
            self.closest_results[session.id] = []
        await self._start_timer(session, entry)
        await self.broadcast_state(session.id)
        await self._persist_snapshot(session, entry)

    async def _start_timer(self, session: Session, entry: dict):
        if entry["kind"] != "question":
            if self.timer_task:
                self.timer_task.cancel()
                self.timer_task = None
            return
        if self.timer_task:
            self.timer_task.cancel()

        async def timer_loop():
            await asyncio.sleep(entry["duration_seconds"])
            from app.db import get_session

            async with get_session() as inner_db:
                fresh = await inner_db.get(Session, session.id)
                if fresh and fresh.manual_override:
                    return
            await self._reveal_current_question(session, entry)
            await asyncio.sleep(entry["gap_seconds"])
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
                await db.refresh(session)

            if not manual and self.active_session_id == session_id and self.current_entry:
                remaining = self.remaining_seconds()
                if remaining <= 0:
                    await self.force_next(session_id)
                else:
                    entry = dict(self.current_entry)
                    entry["duration_seconds"] = remaining
                    await self._start_timer(session, entry)

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
        self.answers.pop(session_id, None)
        self.scores_revealed.pop(session_id, None)
        self.answer_results.pop(session_id, None)
        self.answer_values.pop(session_id, None)
        self.closest_results.pop(session_id, None)
        # Clear players for this session to reset scores/state
        self.players.pop(session_id, None)
        self.player_sockets.pop(session_id, None)

    async def register_player(self, session_id: str, name: str, player_id: Optional[str] = None) -> dict:
        """Ensure a player exists for a session and mark them connected."""
        if session_id not in self.players:
            self.players[session_id] = {}
        session_players = self.players[session_id]
        if player_id and player_id in session_players:
            player = session_players[player_id]
            player["name"] = name or player["name"]
        else:
            player_id = player_id or str(uuid.uuid4())[:8]
            player = {"id": player_id, "name": name or "Player", "score": 0}
            session_players[player_id] = player
        player["connected"] = True
        # Persist player state
        from app.db import get_session

        async with get_session() as db:
            existing = await db.get(SessionPlayer, player_id)
            if existing:
                existing.name = player["name"]
                existing.score = player["score"]
                existing.connected = True
                existing.updated_at = utc_now()
            else:
                db.add(
                    SessionPlayer(
                        id=player_id,
                        session_id=session_id,
                        name=player["name"],
                        score=player["score"],
                        connected=True,
                    )
                )
            await db.commit()
        return player

    async def disconnect_player(self, session_id: str, player_id: Optional[str]):
        if not player_id or session_id not in self.players:
            return
        player = self.players[session_id].get(player_id)
        if player:
            player["connected"] = False
            await self.broadcast_state(session_id)
            from app.db import get_session

            async with get_session() as db:
                db_player = await db.get(SessionPlayer, player_id)
                if db_player:
                    db_player.connected = False
                    db_player.updated_at = utc_now()
                    await db.commit()

    async def add_player_socket(self, session_id: str, websocket):
        sockets = self.player_sockets.setdefault(session_id, [])
        sockets.append(websocket)

    async def remove_player_socket(self, session_id: str, websocket):
        sockets = self.player_sockets.get(session_id)
        if not sockets:
            return
        if websocket in sockets:
            sockets.remove(websocket)

    async def submit_answer(self, session_id: str, player_id: str, answer: Optional[str]) -> bool:
        """Return True if accepted and (when correct) score incremented."""
        if session_id != self.active_session_id or not self.current_entry or self.current_entry["kind"] != "question":
            return False
        if session_id not in self.players or player_id not in self.players[session_id]:
            return False
        if self.current_end and utc_now() > self.current_end:
            return False
        answered = self.answers.setdefault(session_id, set())
        if player_id in answered:
            return False

        question: Question = self.current_entry["question"]
        self.logger.info(
            "Answer received session=%s player=%s question=%s type=%s scoring=%s answer=%r",
            session_id,
            player_id,
            question.id,
            question.answer_type,
            question.scoring_type,
            answer,
        )
        is_correct = False
        score_delta = 0
        if question.scoring_type == "closest":
            # Defer scoring until finalize
            is_correct = False
            score_delta = 0
        elif question.answer_type == "multiple_choice":
            is_correct = answer is not None and answer == question.correct_answer
            score_delta = 1 if is_correct else 0
        elif question.answer_type == "text":
            is_correct = await self._evaluate_text_answer(answer, question.correct_answer)
            score_delta = 1 if is_correct else 0
        else:
            # Placeholder scoring for other freeform types until custom logic is defined
            is_correct = True if answer is not None else False
            score_delta = 1 if is_correct else 0

        if score_delta:
            self.players[session_id][player_id]["score"] += score_delta
            # Persist score bump
            from app.db import get_session

            async with get_session() as db:
                db_player = await db.get(SessionPlayer, player_id)
                if db_player:
                    db_player.score = self.players[session_id][player_id]["score"]
                    db_player.updated_at = utc_now()
                    await db.commit()
        # Store answer
        from app.db import get_session

        async with get_session() as db:
            db.add(
                SessionAnswer(
                    session_id=session_id,
                    question_id=question.id,
                    player_id=player_id,
                    answer=answer,
                    is_correct=is_correct if question.scoring_type != "closest" else False,
                )
            )
            await db.commit()
        answered.add(player_id)
        if question.scoring_type == "closest":
            self.answer_results.setdefault(session_id, {})[player_id] = None
        else:
            self.answer_results.setdefault(session_id, {})[player_id] = is_correct
        self.answer_values.setdefault(session_id, {})[player_id] = answer
        self.logger.info(
            "Answer recorded session=%s player=%s question=%s is_correct=%s delta=%s",
            session_id,
            player_id,
            question.id,
            is_correct,
            score_delta,
        )
        await self.broadcast_state(session_id)
        await self._maybe_fast_forward_question(session_id)
        return True

    async def broadcast_state(self, session_id: str):
        """Push latest state to all player sockets for a session."""
        sockets = self.player_sockets.get(session_id) or []
        if not sockets:
            return
        state = await self.state(session_id)
        to_remove = []
        for ws in sockets:
            try:
                await ws.send_json({"type": "state", "state": state})
            except Exception:
                to_remove.append(ws)
        for ws in to_remove:
            await self.remove_player_socket(session_id, ws)

    async def state(self, session_id: str) -> dict:
        from app.db import get_session

        async with get_session() as db:
            session = await db.get(Session, session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            if session_id not in self.players:
                await self._load_players_from_db(session_id)

            question_payload = None
            intro_payload = None
            if self.current_entry and session.status == SessionStatus.LIVE:
                if self.current_entry["kind"] == "quiz_intro":
                    quiz = self.current_entry["quiz"]
                    intro_payload = {
                        "quiz_index": self.current_entry["quiz_index"],
                        "quiz_id": quiz.id,
                        "quiz_name": quiz.name,
                        "quiz_description": quiz.description,
                        "question_count": len(self.current_entry["questions"]),
                    }
                elif self.current_entry["kind"] == "question":
                    q: Question = self.current_entry["question"]
                    revealed = bool(self.current_end and utc_now() >= self.current_end)
                    question_payload = {
                        "id": q.id,
                        "quiz_index": self.current_entry["quiz_index"],
                        "question_index": self.current_entry["question_index"],
                        "text": q.text,
                        "images": q.images,
                        "audio": q.audio,
                        "answer_type": q.answer_type,
                        "options": q.options,
                        "scoring_type": q.scoring_type,
                        "duration_seconds": q.duration_seconds,
                        "started_at": self.current_start.isoformat() if self.current_start else None,
                        "closes_at": self.current_end.isoformat() if self.current_end else None,
                        "remaining_seconds": self.remaining_seconds(),
                        "revealed": revealed,
                        "correct_answer": q.correct_answer if revealed else None,
                    }

            return {
                "id": session.id,
                "name": session.name,
                "status": session.status,
                "manual_override": session.manual_override,
                "active_quiz_index": session.active_quiz_index,
                "active_question_index": session.active_question_index,
                "question": question_payload,
                "quiz_intro": intro_payload,
                "stage": self.current_entry["kind"] if self.current_entry else None,
                "players": list(self.players.get(session_id, {}).values()),
                "now": utc_now().isoformat(),
                "scores_revealed": self.scores_revealed.get(session_id, False),
                "answers": self.answer_results.get(session_id, {}),
                "answer_values": self.answer_values.get(session_id, {}),
                "closest_results": self.closest_results.get(session_id, []),
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
            # Intro marker for this quiz
            entries.append(
                {
                    "kind": "quiz_intro",
                    "quiz_index": quiz_idx,
                    "question_index": None,
                    "quiz": link.quiz,
                    "questions": ordered_questions,
                }
            )
            # Each question
            for question_idx, question in enumerate(ordered_questions):
                entries.append(
                    {
                        "kind": "question",
                        "quiz_index": quiz_idx,
                        "question_index": question_idx,
                        "duration_seconds": question.duration_seconds,
                        "gap_seconds": link.quiz.gap_seconds,
                        "question": question,
                    }
                )
        return entries
        return entries

    async def _load_players_from_db(self, session_id: str):
        from app.db import get_session

        async with get_session() as db:
            result = await db.exec(select(SessionPlayer).where(SessionPlayer.session_id == session_id))
            players = result.scalars().all()
            self.players[session_id] = {
                p.id: {"id": p.id, "name": p.name, "score": p.score, "connected": p.connected} for p in players
            }
            # Reset answers cache; will be filled when loading current question
            self.answer_values[session_id] = {}

    async def _persist_snapshot(self, session: Session, entry: dict):
        from app.db import get_session

        async with get_session() as db:
            db.add(
                SessionSnapshot(
                    session_id=session.id,
                    current_index=self.current_index,
                    current_entry_kind=entry.get("kind"),
                    quiz_id=entry.get("quiz").id if entry.get("quiz") else None,
                    question_id=entry.get("question").id if entry.get("question") else None,
                    active_quiz_index=session.active_quiz_index,
                    active_question_index=session.active_question_index,
                    current_start=self.current_start,
                    current_end=self.current_end,
                )
            )
            await db.commit()

    async def resume(self, session_id: str):
        async with self.lock:
            from app.db import get_session

            session_obj: Optional[Session] = None
            async with get_session() as db:
                session = await db.get(Session, session_id)
                if not session:
                    raise HTTPException(status_code=404, detail="Session not found")
                snap_result = await db.exec(
                    select(SessionSnapshot)
                    .where(SessionSnapshot.session_id == session_id)
                    .order_by(SessionSnapshot.created_at.desc())
                    .limit(1)
                )
                snapshot = snap_result.scalars().first()
                if not snapshot:
                    raise HTTPException(status_code=400, detail="No snapshot available to resume")
                self.timeline = await self._build_timeline(session_id, db)
                if snapshot.current_index >= len(self.timeline):
                    raise HTTPException(status_code=400, detail="Snapshot is out of range for current timeline")

                self.active_session_id = session_id
                self.current_index = snapshot.current_index
                self.current_entry = self.timeline[self.current_index]
                self.current_start = snapshot.current_start
                self.current_end = snapshot.current_end

                session.status = SessionStatus.LIVE
                session.active_quiz_index = snapshot.active_quiz_index
                session.active_question_index = snapshot.active_question_index
                session_obj = session
                await db.commit()

            await self._load_players_from_db(session_id)
            # Load answered players for current question
            if self.current_entry and self.current_entry.get("kind") == "question":
                from app.db import get_session

                async with get_session() as db:
                    answers = await db.exec(
                        select(SessionAnswer.player_id, SessionAnswer.is_correct, SessionAnswer.answer).where(
                            SessionAnswer.session_id == session_id,
                            SessionAnswer.question_id == self.current_entry["question"].id,
                        )
                    )
                    rows = answers.fetchall()
                    self.answers[session_id] = {row[0] for row in rows}
                    self.answer_results[session_id] = {row[0]: row[1] for row in rows}
                    self.answer_values[session_id] = {row[0]: row[2] for row in rows}
                    # reset closest results; will rebuild on finalize
                    self.closest_results[session_id] = []

            if (
                session_obj
                and self.current_entry
                and self.current_entry.get("kind") == "question"
                and self.current_end
                and not session_obj.manual_override
            ):
                remaining = max(0, int((self.current_end - utc_now()).total_seconds()))
                if remaining > 0:
                    adjusted = dict(self.current_entry)
                    adjusted["duration_seconds"] = remaining
                    await self._start_timer(session_obj, adjusted)
                else:
                    # If expired, move forward
                    await self._reveal_current_question(session_obj, self.current_entry)
                    await self.force_next(session_id)

            await self.broadcast_state(session_id)

    async def _finalize_question_scores(self, session_id: str, question: Question):
        """Compute scores for closest-to-target numeric questions."""
        if question.scoring_type != "closest" and not (
            question.answer_type == "numeric" and not question.scoring_type
        ):
            return
        # Need a numeric target
        try:
            target = float(question.correct_answer)
        except (TypeError, ValueError):
            return

        from app.db import get_session

        async with get_session() as db:
            result = await db.exec(
                select(SessionAnswer).where(
                    SessionAnswer.session_id == session_id, SessionAnswer.question_id == question.id
                )
            )
            answers = result.scalars().all()

            parsed = []
            for ans in answers:
                try:
                    val = float(ans.answer) if ans.answer is not None else None
                except (TypeError, ValueError):
                    val = None
                if val is None:
                    continue
                diff = abs(val - target)
                parsed.append((ans, diff))

            if not parsed:
                return

            min_diff = min(d for _, d in parsed)
            max_diff = max(d for _, d in parsed)
            range_diff = max_diff - min_diff

            updates = []
            for ans, diff in parsed:
                base_score = 1.0
                if range_diff > 0:
                    base_score = 1.0 - ((diff - min_diff) / range_diff)
                score = base_score
                if diff == 0:
                    score += 0.5
                score = max(0.0, min(1.5, score))
                updates.append((ans.player_id, score, diff == 0))

            # Apply scores and store ranking
            closest_list = []
            for ans, diff in parsed:
                closest_list.append(
                    {
                        "player_id": ans.player_id,
                        "answer": ans.answer,
                        "distance": diff,
                        "is_exact": diff == 0,
                    }
                )

            closest_list.sort(key=lambda x: x["distance"])
            self.closest_results[session_id] = closest_list
            self.logger.info(
                "Closest scoring session=%s question=%s target=%s entries=%s",
                session_id,
                question.id,
                target,
                closest_list,
            )

            for entry in closest_list:
                player_id = entry["player_id"]
                delta = next((d for pid, d, _ in updates if pid == player_id), 0)
                is_exact = entry["is_exact"]
                player = self.players.get(session_id, {}).get(player_id)
                if player:
                    player["score"] += delta
                db_player = await db.get(SessionPlayer, player_id)
                if db_player:
                    db_player.score = (db_player.score or 0) + delta
                    db_player.updated_at = utc_now()
                for ans in answers:
                    if ans.player_id == player_id:
                        ans.is_correct = is_exact or delta > 0
                self.answer_results.setdefault(session_id, {})[player_id] = is_exact

            await db.commit()

    async def _evaluate_text_answer(self, answer: Optional[str], target: Optional[str]) -> bool:
        return await evaluate_text_answer(answer, target)

    async def set_scores_revealed(self, session_id: str, reveal: bool):
        self.scores_revealed[session_id] = reveal
        await self.broadcast_state(session_id)

    async def _get_session_obj(self, session_id: str) -> Optional[Session]:
        from app.db import get_session

        async with get_session() as db:
            return await db.get(Session, session_id)

    async def _reveal_current_question(self, session: Session, entry: dict):
        if entry.get("kind") != "question":
            return
        if not self.current_finalized:
            await self._finalize_question_scores(session.id, entry["question"])
            self.current_finalized = True
        # When revealing early (e.g., all players answered), mark the end as now
        self.current_end = utc_now()
        await self.broadcast_state(session.id)

    async def _maybe_fast_forward_question(self, session_id: str):
        if self.active_session_id != session_id or not self.current_entry or self.current_entry.get("kind") != "question":
            return
        players = self.players.get(session_id, {})
        active_players = {pid: p for pid, p in players.items() if p.get("connected")}
        if not active_players:
            return
        answered = self.answers.get(session_id, set())
        if len(answered) < len(active_players):
            return
        # All players answered: reveal now and skip to gap timer
        if self.timer_task:
            self.timer_task.cancel()
        gap = self.current_entry.get("gap_seconds", 0)

        async def gap_then_next():
            session_obj = await self._get_session_obj(session_id)
            if session_obj and self.current_entry:
                await self._reveal_current_question(session_obj, self.current_entry)
            if gap > 0:
                await asyncio.sleep(gap)
            await self.force_next(session_id)

        self.timer_task = asyncio.create_task(gap_then_next())


runtime = RuntimeController()
