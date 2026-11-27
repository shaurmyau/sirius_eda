"""API администрирования промокодов. Доступно только администратору."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import require_permission
from app.database import get_db
from app.entities import User
from app.modules.promotions.repository import PromoCodeRepository
from app.modules.promotions.service import PromoCodeService
from app.permissions import Perm
from app.schemas import PromoCodeCreate

router = APIRouter()


def get_promo_service(db: Session = Depends(get_db)) -> PromoCodeService:
    return PromoCodeService(PromoCodeRepository(db))


def _serialize(row):
    return {
        "id": row.id, "code": row.code, "discount_type": row.discount_type,
        "discount_value": str(row.discount_value), "valid_from": row.valid_from.isoformat(),
        "valid_until": row.valid_until.isoformat(), "max_uses": row.max_uses,
        "current_uses": row.current_uses, "min_order_amount": str(row.min_order_amount),
        "is_active": row.is_active,
    }


@router.post("")
def create_promo_code(
    payload: PromoCodeCreate,
    _admin: User = Depends(require_permission("*")),
    service: PromoCodeService = Depends(get_promo_service),
):
    try:
        row = service.create(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "promo_code": _serialize(row)}


@router.get("")
def list_promo_codes(
    _admin: User = Depends(require_permission("*")),
    service: PromoCodeService = Depends(get_promo_service),
):
    return {"status": "success", "promo_codes": [_serialize(row) for row in service.list_all()]}
