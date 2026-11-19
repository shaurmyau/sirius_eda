"""Транспортный слой users. RBAC: users:read, users:topup:self/any."""
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_user_service
from app.core.dependencies import (get_current_user,
                                   get_current_user_optional,
                                   require_permission)
from app.core.config import settings
from app.entities import User
from app.http_errors import to_http_error
from app.modules.users.service import UserService
from app.permissions import Perm
from app.schemas import UserCreate

router = APIRouter()


@router.post("/register")
def register_user(
    payload: UserCreate,
    current_user: User | None = Depends(get_current_user_optional),
    service: UserService = Depends(get_user_service),
):
    if payload.phone and len(payload.phone) < 10:
        raise HTTPException(400, "Некорректный формат номера телефона")
    if len(payload.password) < 6:
        raise HTTPException(400, "Пароль должен быть не короче 6 символов")

    role = (payload.role or "student").lower()

    # ВНИМАНИЕ: роль принимается от любого клиента — это открывает
    # privilege escalation. В учебном режиме допустимо; в продакшене
    # верните проверку users:assign_role или флаг ALLOW_SELF_ROLE_ASSIGN.
    # См. README → «Регистрация с выбором роли».

    try:
        u = service.register_user(payload.email, payload.password, payload.phone, role=role)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "user_id": u.id, "email": u.email, "role": u.role}


@router.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email,
            "balance": current_user.balance, "role": current_user.role,
            "permissions": sorted(current_user.effective_permissions())}


@router.post("/me/topup")
def top_up_my_balance(amount: float,
                      current_user: User = Depends(require_permission(Perm.USERS_TOPUP_SELF)),
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


    if current_user.id == user_id:
        if not current_user.has_permission(Perm.USERS_TOPUP_SELF):
            raise HTTPException(403, "Требуется право: users:topup:self")
    else:
        if not current_user.has_permission(Perm.USERS_TOPUP_ANY):
            raise HTTPException(403, "Требуется право: users:topup:any")

    try:
        nb = service.top_up_balance(user_id, amount)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "new_balance": nb}
