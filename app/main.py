from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import admin, root
from app.core.config import settings
from app.db import init_db
from app.api.ws import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure media directory exists before serving uploads
    settings.media_root.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield

app = FastAPI(title="Christmas Quiz", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory=settings.media_root), name="media")

# HTTP routes
app.include_router(root.router)
app.include_router(admin.router)

# WebSocket routes
app.include_router(ws_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
