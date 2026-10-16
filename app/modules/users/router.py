"""Транспортный слой users."""
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_user_service
from app.core.dependencies import get_current_user
from app.entities import User
from app.http_errors import to_http_error
from app.modules.users.service import UserService
from app.schemas import UserCreate

router = APIRouter()


@router.post("/register")
def register_user(payload: UserCreate, service: UserService = Depends(get_user_service)):
    if payload.phone and len(payload.phone) < 10:
        raise HTTPException(400, "Некорректный формат номера телефона")
    if len(payload.password) < 6:
        raise HTTPException(400, "Пароль должен быть не короче 6 символов")
    try:
        u = service.register_user(payload.email, payload.password, payload.phone)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "user_id": u.id, "email": u.email}


@router.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email,
            "balance": current_user.balance, "role": current_user.role}


@router.post("/me/topup")
def top_up_my_balance(amount: float,
                      current_user: User = Depends(get_current_user),
                      service: UserService = Depends(get_user_service)):
    if amount <= 0:
        raise HTTPException(400, "Сумма пополнения должна быть положительной")
    try:
        nb = service.top_up_balance(current_user.id, amount)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "new_balance": nb}


@router.post("/{user_id}/topup")
def top_up_balance(user_id: int, amount: float,
                   current_user: User = Depends(get_current_user),
                   service: UserService = Depends(get_user_service)):
    if amount <= 0:
        raise HTTPException(400, "Сумма пополнения должна быть положительной")
    # IDOR: пополнить чужой баланс может только admin.
    if current_user.id != user_id and current_user.role != "admin":
        raise HTTPException(403, "Доступ запрещён")
    try:
        nb = service.top_up_balance(user_id, amount)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "new_balance": nb}
