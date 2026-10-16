"""Бизнес-логика auth. Refresh Token rotation."""
from datetime import datetime, timedelta, timezone

from jose import JWTError

from app.core.config import settings
from app.core.jwt import create_access_token, create_refresh_token, decode_token
from app.core.security import verify_password
from app.exceptions import ForbiddenError, UnauthorizedError
from app.modules.auth.repository import AuthRepository


class AuthService:
    def __init__(self, repository: AuthRepository):
        self.repository = repository

    def login(self, email, password) -> dict:
        u = self.repository.get_user_by_email(email)
        if not u or not verify_password(password, u.password_hash or ""):
            raise UnauthorizedError("Неверный email или пароль")
        if u.is_blocked:
            raise ForbiddenError("Пользователь заблокирован")
        access = create_access_token(u.id, role=u.role)
        refresh, jti = create_refresh_token(u.id)
        exp = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        self.repository.save_refresh_token(u.id, jti, refresh, exp)
        return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}

    def refresh(self, refresh_token) -> dict:
        try:
            payload = decode_token(refresh_token)
        except JWTError:
            raise UnauthorizedError("Недействительный refresh-токен")
        if payload.get("type") != "refresh":
            raise UnauthorizedError("Неверный тип токена")
        jti = payload.get("jti"); uid = int(payload.get("sub", 0))
        if not jti or not uid:
            raise UnauthorizedError("Недействительный refresh-токен")

        # Rotation: повторное использование отозванного токена = компрометация.
        if self.repository.is_refresh_token_revoked(jti):
            self.repository.revoke_all_user_tokens(uid)
            raise UnauthorizedError("Refresh-токен уже использован. Сессия сброшена")
        if not self.repository.is_refresh_token_valid(jti, refresh_token):
            self.repository.revoke_all_user_tokens(uid)
            raise UnauthorizedError("Недействительный refresh-токен")

        u = self.repository.get_user_by_id(uid)
        if not u: raise UnauthorizedError("Пользователь не найден")
        if u.is_blocked: raise ForbiddenError("Пользователь заблокирован")

        self.repository.revoke_refresh_token(jti)
        new_access = create_access_token(u.id, role=u.role)
        new_refresh, new_jti = create_refresh_token(u.id)
        exp = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        self.repository.save_refresh_token(u.id, new_jti, new_refresh, exp)
        return {"access_token": new_access, "refresh_token": new_refresh, "token_type": "bearer"}
