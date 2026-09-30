"""
Модуль инициализации подключения к СУБД PostgreSQL.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://sirius:sirius@localhost:5432/sirius_food",
)

# echo=True выводит SQL-запросы (INSERT, UPDATE) в терминал; отключается SQL_ECHO=0
engine = create_engine(DATABASE_URL, echo=os.getenv("SQL_ECHO", "1") == "1")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Генератор сессии базы данных для использования в Depends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
