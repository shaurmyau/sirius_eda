"""Репозиторий управления промокодами."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PromoCode


class PromoCodeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_code(self, code: str):
        return self.db.query(PromoCode).filter(PromoCode.code == code).first()

    def create(self, **values):
        row = PromoCode(**values)
        try:
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            return row
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError("Промокод с таким кодом уже существует") from exc

    def list_all(self):
        return self.db.query(PromoCode).order_by(PromoCode.id.desc()).all()
