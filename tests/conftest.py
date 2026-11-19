"""Общие фикстуры.

Переменные окружения выставляются ДО импорта app.* (Settings читается один раз),
поэтому порядок сбора тестов (в т.ч. tests/integration/) не влияет на результат.
"""
import os

os.environ["REPO_BACKEND"] = "memory"
os.environ["RATE_LIMIT_ENABLED"] = "False"

import pytest  # noqa: E402


@pytest.fixture
def session_factory(tmp_path):
    """Изолированная SQLite-БД со всеми таблицами проекта (без PostgreSQL)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import models  # noqa: F401 — регистрация ORM-моделей
    from app.database import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()
