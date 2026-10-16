"""Подключение к СУБД."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://sirius:sirius@localhost:5432/sirius_food",
)

engine = create_engine(DATABASE_URL, echo=os.getenv("SQL_ECHO", "0") == "1")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
