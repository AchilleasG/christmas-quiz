# Christmas Quiz (MVP)

A lightweight FastAPI + WebSocket prototype for running a living-room quiz: admin on one device, players join from phones. State and timers are broadcast in real time.

## Prerequisites
- Python 3.11+ recommended
- pip
- PostgreSQL (set `QUIZ_DATABASE_URL`, default: `postgresql+asyncpg://postgres:postgres@localhost:5432/christmas_quiz`)

### Environment
- Copy `.env.example` to `.env` and edit for your Postgres connection.
- You can set a full `QUIZ_DATABASE_URL`, or use the separate params: `QUIZ_DB_HOST`, `QUIZ_DB_PORT`, `QUIZ_DB_NAME`, `QUIZ_DB_USER`, `QUIZ_DB_PASSWORD` (URL wins if both are set).
- `QUIZ_CORS_ORIGINS` accepts a comma-separated list or `*`. Settings use the `QUIZ_` prefix and load from `.env` automatically.

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8003
```

Open in browser:
- Admin UI: `http://localhost:8003/static/admin.html`
- Player UI: `http://localhost:8003/` (serves `static/player.html`)

## Project layout
- `app/main.py` – FastAPI entrypoint, routers mounting, DB init
- `app/api/routes/` – HTTP routes (`root`, admin CRUD/start/control)
- `app/api/ws/` – (currently unused) websockets; will be revisited
- `app/models/` – SQLModel ORM models (quizzes, questions, sessions)
- `app/schemas/` – Pydantic models for admin payloads and session state
- `app/services/` – Runtime controller for live sessions
- `static/` – Basic admin/player HTML for the MVP (outdated vs new flows)

## Notes
- Quiz/question/session definitions persist in Postgres; runtime state remains in-memory for now.
- Media for questions should be provided as URLs when creating quizzes (no uploads yet).

## Media uploads
- Endpoint: `POST /admin/upload` with form fields `kind` (`image` or `audio`) and `file` (multipart).
- Stored under `media/images` or `media/audio`; served at `/media/...`.
- Allowed types: images (`png`, `jpeg`, `jpg`, `gif`); audio (`mp3`, `mpeg`, `wav`, `ogg`).

## Docker
- Build & run app (expects external Postgres via `.env`):
  ```bash
  docker compose up --build
  ```
- Exposes the app on host port `8003` (mapped to container `8000`).
- Media persists in volume `media-data` mapped to `/app/media`.
- Ensure `.env` points to your external DB (`QUIZ_DB_*` or `QUIZ_DATABASE_URL`).
- Run migrations inside the container:
  ```bash
  docker compose run --rm app alembic upgrade head
  ```

## Realtime
- Admin dashboard uses a websocket at `/ws/admin/{session_id}` to stream live session/question state (1s ticks for timers).
- Player-facing websockets to be added once the player flow is rebuilt on the DB-backed runtime.

## Migrations (Alembic)
- Config lives in `alembic.ini` and `alembic/`.
- Uses `QUIZ_DATABASE_URL` from env (defaults to Postgres).
- Generate a new revision after model changes:
  ```bash
  alembic revision --autogenerate -m "describe change"
  ```
- Apply migrations:
  ```bash
  alembic upgrade head
  ```
