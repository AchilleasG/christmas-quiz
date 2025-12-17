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


@router.websocket("/ws/player/{session_id}")
async def player_socket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    player_id = None
    sender_task = None
    try:
        join_msg = await websocket.receive_json()
        if join_msg.get("type") != "join":
            await websocket.close()
            return
        name = join_msg.get("name") or "Player"
        player_id = join_msg.get("player_id")
        player = await runtime.register_player(session_id, name, player_id)
        player_id = player["id"]
        await runtime.add_player_socket(session_id, websocket)
        await websocket.send_json({"type": "welcome", "player": player})

        async def send_loop():
            while True:
                state = await runtime.state(session_id)
                await websocket.send_json({"type": "state", "state": state})
                await asyncio.sleep(1)

        sender_task = asyncio.create_task(send_loop())

        while True:
            message = await websocket.receive_json()
            if message.get("type") == "answer":
                await runtime.submit_answer(session_id, player_id, message.get("answer"))
    except WebSocketDisconnect:
        return
    finally:
        if sender_task:
            sender_task.cancel()
        await runtime.remove_player_socket(session_id, websocket)
        await runtime.disconnect_player(session_id, player_id)
