import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.runtime import runtime

router = APIRouter()


@router.websocket("/ws/admin/{session_id}")
async def admin_state_socket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        while True:
            state = await runtime.state(session_id)
            await websocket.send_json({"type": "state", "state": state})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
