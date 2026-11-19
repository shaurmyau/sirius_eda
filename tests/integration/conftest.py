"""Фикстуры интеграционных тестов.

Брокер берём так:
  1) RABBITMQ_TEST_URL, если задан (ВНИМАНИЕ: тесты удаляют очереди проекта на этом брокере);
  2) иначе поднимаем одноразовый контейнер через testcontainers (нужен Docker);
  3) иначе тесты пропускаются (skip), а не падают.
"""
import asyncio
import os
import time

import pytest

aio_pika = pytest.importorskip("aio_pika")

from app.core.rabbitmq import ALL_QUEUES, DLX_EXCHANGE_NAME, EXCHANGE_NAME  # noqa: E402

PROBE_QUEUE = "test_probe_cancelled"


async def _try_connect(url: str) -> None:
    connection = await aio_pika.connect(url, timeout=3)
    await connection.close()


def _wait_for_broker(url: str, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            asyncio.run(_try_connect(url))
            return
        except Exception as exc:
            last = exc
            time.sleep(1)
    raise RuntimeError(f"RabbitMQ в контейнере не поднялся за {timeout}с: {last!r}")


@pytest.fixture(scope="session")
def rabbit_url():
    url = os.getenv("RABBITMQ_TEST_URL")
    if url:
        yield url
        return

    try:
        from docker.types import Ulimit
        from testcontainers.core.container import DockerContainer
    except ImportError:
        pytest.skip("testcontainers не установлен: pip install testcontainers")

    container = None
    try:
        container = (DockerContainer("rabbitmq:3.13-management")
                     .with_exposed_ports(5672)
                     .with_env("RABBITMQ_DEFAULT_USER", "sirius")
                     .with_env("RABBITMQ_DEFAULT_PASS", "sirius")
                     .with_kwargs(ulimits=[Ulimit(name="nofile", soft=65536, hard=65536)]))
        container.start()
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5672)
        url = f"amqp://sirius:sirius@{host}:{port}/"
        _wait_for_broker(url)
    except Exception as exc:
        if container is not None:
            try:
                container.stop()
            except Exception:
                pass
        pytest.skip(f"Docker/RabbitMQ недоступен: {exc!r}")
    try:
        yield url
    finally:
        container.stop()


async def _reset(url: str) -> None:
    connection = await aio_pika.connect_robust(url)
    async with connection:
        channel = await connection.channel()
        names = [PROBE_QUEUE]
        for q in ALL_QUEUES:
            names += [q.name, q.dlq_name]
        for name in names:
            await channel.queue_delete(name)
        for exchange in (EXCHANGE_NAME, DLX_EXCHANGE_NAME):
            await channel.exchange_delete(exchange)


@pytest.fixture
def broker(rabbit_url):
    """Чистый брокер для каждого теста (очереди и exchange'ы удаляются)."""
    asyncio.run(_reset(rabbit_url))
    yield rabbit_url
    asyncio.run(_reset(rabbit_url))
