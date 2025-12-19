from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def root():
    with open("static/player.html", "r", encoding="utf-8") as f:
        return f.read()


@router.get("/admin", response_class=HTMLResponse)
async def admin_page():
    with open("static/admin.html", "r", encoding="utf-8") as f:
        return f.read()


@router.get("/presenter", response_class=HTMLResponse)
async def presenter_page():
    with open("static/presenter.html", "r", encoding="utf-8") as f:
        return f.read()
