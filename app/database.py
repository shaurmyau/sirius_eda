"""Подключение к СУБД."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings
from app.core.metrics import instrument_sqlalchemy_engine

DATABASE_URL = settings.DATABASE_URL

engine = create_engine(DATABASE_URL, echo=os.getenv("SQL_ECHO", "0") == "1")
instrument_sqlalchemy_engine(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_permissions() -> None:
    """Идемпотентно создаёт permissions и связывает их с ролями.

    Вызывается из main.py при старте приложения. Безопасно вызывать
    многократно: существующие записи не дублируются.
    """
    from app.models import Permission, Role  # локальный импорт во избежание циклов
    from app.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS

    db = SessionLocal()
    try:
        # 1. Права
        existing = {p.code: p for p in db.query(Permission).all()}
        for code, desc in ALL_PERMISSIONS.items():
            if code not in existing:
                obj = Permission(code=code, description=desc)
                db.add(obj)
                existing[code] = obj
        db.flush()

        # 2. Роли + связи
        for role_name, codes in ROLE_PERMISSIONS.items():
            role = db.query(Role).filter(Role.name == role_name).first()
            if not role:
                role = Role(name=role_name, description=f"Роль {role_name}")
                db.add(role)
                db.flush()
            role.permissions = []
            if codes == {"*"}:
                role.permissions = list(existing.values())
            else:
                role.permissions = [existing[c] for c in codes if c in existing]
        db.commit()
    finally:
        db.close()
