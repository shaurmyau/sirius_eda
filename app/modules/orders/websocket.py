"""WebSocket endpoint для realtime-трекинга заказа (трек B)."""
import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError

from app.core.config import settings
from app.core.jwt import decode_token
from app.core.websocket_manager import order_ws_manager
from app.container import use_memory_backend
from app.database import SessionLocal
from app.memory_store import memory_store
from app.models import Order as OrderModel, User as UserModel

router = APIRouter()
log = logging.getLogger("orders.websocket")


def _load_order_access(order_id: int, user_id: int) -> str | None:
    """Короткая DB-сессия: проверяем существование пользователя и владение заказом."""
    if use_memory_backend():
        user = memory_store.users.get(user_id)
        order = memory_store.orders.get(order_id)
    else:
        db = SessionLocal()
        try:
            user = db.query(UserModel).filter(UserModel.id == user_id).first()
            row = db.query(OrderModel).filter(OrderModel.id == order_id).first()
            order = row
        finally:
            db.close()
    if user is None or getattr(user, "is_blocked", False):
        return None
    if order is None or int(order.user_id) != int(user_id):
        return None
    status = order.status
    # Внутренний статус оплаты соответствует внешнему этапу приготовления.
    return "preparing" if status == "paid" else status


@router.websocket("/ws/orders/{order_id}")
async def track_order(
    websocket: WebSocket,
    order_id: int,
    token: str | None = Query(default=None),
):
    if not token:
        await websocket.close(code=1008, reason="Требуется access JWT")
        return
    try:
        claims = decode_token(token)
        if claims.get("type") != "access":
            raise ValueError("Неверный тип JWT")
        user_id = int(claims["sub"])
    except (JWTError, KeyError, TypeError, ValueError):
        await websocket.close(code=1008, reason="Недействительный access JWT")
        return

    current_status = _load_order_access(order_id, user_id)
    if current_status is None:
        await websocket.close(code=1008, reason="Заказ не найден или принадлежит другому пользователю")
        return

    await order_ws_manager.connect(websocket, order_id)
    try:
        # Snapshot при каждом подключении/переподключении закрывает пропуск событий.
        await websocket.send_json({"type": "snapshot", "order_id": order_id, "status": current_status})
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(), timeout=settings.WS_HEARTBEAT_INTERVAL_SECONDS
                )
                if isinstance(message, dict) and message.get("type") == "pong":
                    continue
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                try:
                    pong = await asyncio.wait_for(
                        websocket.receive_json(), timeout=settings.WS_HEARTBEAT_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    log.info("WebSocket heartbeat timeout: order_id=%s user_id=%s", order_id, user_id)
                    break
                if not isinstance(pong, dict) or pong.get("type") != "pong":
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("WebSocket connection closed: order_id=%s user_id=%s", order_id, user_id, exc_info=True)
    finally:
        order_ws_manager.disconnect(websocket, order_id)
