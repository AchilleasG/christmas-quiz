from app.db import get_session
from app.services.session_manager import SessionStore

session_store = SessionStore()


def get_session_store() -> SessionStore:
    return session_store


async def get_db_session():
    async with get_session() as session:
        yield session
