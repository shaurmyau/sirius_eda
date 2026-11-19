"""Помощники интеграционных тестов: запуск consumer'ов на реальном брокере."""
import asyncio
from collections import namedtuple
from contextlib import asynccontextmanager

import aio_pika

from app.core.rabbitmq import declare_topology
from app.workers.base import start_consumer

Env = namedtuple("Env", "channel exchange queues")


@asynccontextmanager
async def running_consumers(url, specs, session_factory):
    """Поднимает consumer'ы на реальном RabbitMQ и отдаёт exchange для публикации."""
    connection = await aio_pika.connect_robust(url)
    try:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=10)
        exchange, queues = await declare_topology(channel)
        for spec in specs:
            await start_consumer(channel, spec, session_factory)
        yield Env(channel, exchange, queues)
    finally:
        await connection.close()


async def wait_until(predicate, timeout: float = 15.0, interval: float = 0.1) -> bool:
    """Ждёт, пока predicate() станет истинным (consumer'ы работают асинхронно)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return bool(predicate())


async def get_message(queue, timeout: float = 15.0):
    """Забирает одно сообщение из очереди (polling) или None по таймауту."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        message = await queue.get(fail=False, no_ack=True)
        if message is not None:
            return message
        await asyncio.sleep(0.1)
    return None
