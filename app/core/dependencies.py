"""FastAPI-зависимости: get_current_user, require_role, require_permission."""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.container import get_user_repository
from app.core.jwt import decode_token
from app.entities import User
from app.modules.users.repository import UserRepository
from app.permissions import ROLE_PERMISSIONS

bearer = HTTPBearer(auto_error=True)
bearer_optional = HTTPBearer(auto_error=False)


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


def require_permission(*codes: str):
    """Dependency: у пользователя должно быть хотя бы одно из указанных прав.

    Пример: require_permission(Perm.MENU_WRITE) — только cook/admin.
    """
    required = set(codes)

    def checker(current_user: User = Depends(get_current_user)) -> User:
        if not any(current_user.has_permission(c) for c in required):
            raise HTTPException(403, f"Требуется право: {', '.join(sorted(required))}")
        return current_user

    return checker


# Псевдоним для обратной совместимости и удобства.
def require_role(role: str):
    """Оставлено для совместимости. Внутри превращается в проверку
    «у пользователя есть хотя бы одно право этой роли»."""
    role_perms = ROLE_PERMISSIONS.get(role, set())
    if not role_perms:
        role_perms = {"*"}  # на случай кастомной роли — считаем admin-подобной
    return require_permission(*role_perms)


def get_current_user_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_optional),
    repo: UserRepository = Depends(get_user_repository),
) -> User | None:
    """Как get_current_user, но возвращает None, если токена нет/он невалиден.

    Нужно для эндпоинтов, где анонимный доступ разрешён, но мы хотим
    знать, кто именно пришёл (например /users/register с ролью).
    """
    if creds is None:
        return None
    try:
        payload = decode_token(creds.credentials)
        if payload.get("type") != "access":
            return None
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
    user = repo.get_user_by_id(user_id)
    if not user or user.is_blocked:
        return None
    return user
