"""API личного кабинета программы лояльности."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.entities import User
from app.modules.loyalty.repository import LoyaltyRepository
from app.modules.loyalty.service import LoyaltyService

router = APIRouter()


@router.get("/me")
def my_loyalty(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"status": "success", "loyalty": LoyaltyService(LoyaltyRepository(db)).get_summary(current_user.id)}
