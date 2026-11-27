"""Репозиторий управления промокодами."""
from sqlalchemy.orm import Session

from app.models import PromoCode


class PromoCodeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_code(self, code: str):
        return self.db.query(PromoCode).filter(PromoCode.code == code).first()

    def create(self, **values):
        row = PromoCode(**values)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_all(self):
        return self.db.query(PromoCode).order_by(PromoCode.id.desc()).all()
