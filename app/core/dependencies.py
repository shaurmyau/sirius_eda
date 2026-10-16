"""FastAPI-зависимости: get_current_user и require_role."""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.container import get_user_repository
from app.core.jwt import decode_token
from app.entities import User
from app.modules.users.repository import UserRepository

bearer = HTTPBearer(auto_error=True)


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    repo: UserRepository = Depends(get_user_repository),
) -> User:
    try:
        payload = decode_token(creds.credentials)
        if payload.get("type") != "access":
            raise HTTPException(401, "Неверный тип токена")
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Недействительный токен")

    user = repo.get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "Пользователь не найден")
    if user.is_blocked:
        raise HTTPException(403, "Пользователь заблокирован")
    return user


def require_role(role: str):
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role != role and current_user.role != "admin":
            raise HTTPException(403, "Доступ запрещён")
        return current_user

    return checker
