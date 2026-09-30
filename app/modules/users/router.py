"""
Транспортный слой модуля users (Круг 4).
"""
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_user_service
from app.http_errors import to_http_error
from app.modules.users.service import UserService
from app.schemas import UserCreate

router = APIRouter()


@router.post("/register")
def register_user(payload: UserCreate, service: UserService = Depends(get_user_service)):
    # Техническая валидация (формат email уже проверил Pydantic).
    if payload.phone and len(payload.phone) < 10:
        raise HTTPException(status_code=400, detail="Некорректный формат номера телефона")

    try:
        user = service.register_user(payload.email, payload.phone)
    except ValueError as e:
        raise to_http_error(e)

    return {"status": "success", "user_id": user.id, "email": user.email}


@router.post("/{user_id}/topup")
def top_up_balance(
    user_id: int,
    amount: float,
    service: UserService = Depends(get_user_service),
):
    # Техническая проверка положительности суммы пополнения.
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма пополнения должна быть положительной")

    try:
        new_balance = service.top_up_balance(user_id, amount)
    except ValueError as e:
        raise to_http_error(e)

    return {"status": "success", "new_balance": new_balance}
