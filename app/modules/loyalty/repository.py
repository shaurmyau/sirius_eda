"""Репозиторий программы лояльности."""
from sqlalchemy.orm import Session

from app.models import LoyaltyAccount


class LoyaltyRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_user_id(self, user_id: int):
        return self.db.query(LoyaltyAccount).filter(LoyaltyAccount.user_id == user_id).first()

    def get_or_create(self, user_id: int):
        row = self.get_by_user_id(user_id)
        if row is None:
            row = LoyaltyAccount(user_id=user_id, balance=0, total_earned=0, tier="Bronze")
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return row
