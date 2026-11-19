"""Настройка DLQ-инфраструктуры. Можно запускать сколько угодно раз.

Создаёт dlx_exchange, очереди *_dlq, основные очереди и bindings.
Запуск:  python -m app.workers.dlq_setup
"""
import asyncio

from app.core.rabbitmq import ALL_QUEUES, declare_topology, get_connection


async def setup() -> None:
    connection = await get_connection()
    async with connection:
        channel = await connection.channel()
        await declare_topology(channel)
    names = ", ".join(q.dlq_name for q in ALL_QUEUES)
    print(f"DLQ настроена: dlx_exchange + {names}")


if __name__ == "__main__":
    asyncio.run(setup())
