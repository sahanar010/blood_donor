import asyncio

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.db import SessionLocal
from app.models import User
from app.realtime import hub
from app.security import decode_token

router = APIRouter(tags=["realtime"])

IDLE_TIMEOUT_SECONDS = 90   # clients should send "ping" about every 30 s


def _authenticate(token: str) -> tuple[int, str] | None:
    try:
        payload = decode_token(token)
        with SessionLocal() as db:
            user = db.get(User, int(payload["sub"]))
            if user and user.is_active:
                return user.id, user.role.value
    except (jwt.PyJWTError, KeyError, ValueError):
        pass
    return None


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query(...)):
    """Connect with  ws://host/ws?token=<JWT from /auth/login>.

    Server -> client: {"type": ..., "data": ..., "ts": ...}. Client -> server: send "ping"
    periodically (answers {"type":"pong"}); it keeps the connection and your online presence alive.
    """
    ident = await asyncio.to_thread(_authenticate, token)
    if ident is None:
        await websocket.close(code=4401)   # invalid/expired token: handshake rejected
        return
    user_id, role = ident

    await websocket.accept()
    await hub.connect(user_id, websocket)
    try:
        await websocket.send_json({"type": "connected", "data": {"role": role}})
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=IDLE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                await websocket.close(code=4408)   # idle too long
                break
            if msg.strip().strip('"').lower() == "ping" or '"ping"' in msg:
                await hub.touch(user_id)
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(user_id, websocket)
