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
    except ImportError as exc:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"RabbitMQ Testcontainers dependency missing in CI: {exc}")
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
        if os.getenv("CI", "").lower() == "true":
            pytest.fail(f"Docker/RabbitMQ недоступен в CI: {exc!r}")
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


@pytest.fixture(scope="session")
def postgres_url():
    """Одноразовая PostgreSQL 15 с production-схемой, накатываемой Alembic."""
    from app.core.config import settings

    container = None
    url = os.getenv("POSTGRES_TEST_URL")
    if not url:
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError as exc:
            if os.getenv("CI", "").lower() == "true":
                pytest.fail(f"PostgreSQL Testcontainers dependency missing: {exc}")
            pytest.skip("Установите testcontainers[postgres] для PostgreSQL integration tests")

        container = PostgresContainer(
            "postgres:15",
            username="sirius_test",
            password="sirius_test",
            dbname="sirius_test",
        )
        try:
            container.start()
            url = container.get_connection_url()
        except Exception as exc:
            try:
                container.stop()
            except Exception:
                pass
            if os.getenv("CI", "").lower() == "true":
                pytest.fail(f"PostgreSQL Testcontainer не запустился в CI: {exc!r}")
            pytest.skip(f"Docker/PostgreSQL недоступен: {exc!r}")

    original_url = settings.DATABASE_URL
    settings.DATABASE_URL = url
    try:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        # ConfigParser treats percent signs as interpolation markers.
        alembic_cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(alembic_cfg, "head")
        yield url
    finally:
        settings.DATABASE_URL = original_url
        if container is not None:
            container.stop()


@pytest.fixture
def postgres_session(postgres_url):
    """Session bound to an outer transaction; repository commits use savepoints."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(postgres_url, pool_pre_ping=True)
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        if outer_transaction.is_active:
            outer_transaction.rollback()
        connection.close()
        engine.dispose()
