"""Локальный реестр WebSocket-соединений и Redis Pub/Sub listener."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from redis.asyncio import Redis
from starlette.websockets import WebSocket

from app.core.config import settings
from app.core.order_updates import ORDER_UPDATES_CHANNEL

log = logging.getLogger("orders.websocket")


class OrderWebSocketManager:
    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, order_id: int) -> None:
        await websocket.accept()
        self.connections[order_id].add(websocket)

    def disconnect(self, websocket: WebSocket, order_id: int) -> None:
        connections = self.connections.get(order_id)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self.connections.pop(order_id, None)

    async def broadcast_local(self, payload: dict) -> None:
        try:
            order_id = int(payload["order_id"])
        except (KeyError, TypeError, ValueError):
            return
        dead = []
        for websocket in tuple(self.connections.get(order_id, ())):
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket, order_id)

    async def run_redis_listener(self) -> None:
        """Каждая реплика подписана на общий канал и доставляет событие своим клиентам."""
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            while True:
                pubsub = client.pubsub()
                try:
                    await pubsub.subscribe(ORDER_UPDATES_CHANNEL)
                    log.info("WebSocket replica subscribed to Redis channel %s", ORDER_UPDATES_CHANNEL)
                    while True:
                        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                        if message and message.get("type") == "message":
                            try:
                                payload = json.loads(message["data"])
                                if isinstance(payload, dict):
                                    await self.broadcast_local(payload)
                            except (TypeError, ValueError, json.JSONDecodeError):
                                log.warning("Некорректное сообщение Redis Pub/Sub")
                        await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.warning("Redis Pub/Sub недоступен; повтор подключения через 2 сек.", exc_info=True)
                    await asyncio.sleep(2)
                finally:
                    await pubsub.aclose()
        finally:
            await client.aclose()


order_ws_manager = OrderWebSocketManager()
