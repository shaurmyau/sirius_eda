"""Бизнес-логика users."""
from app.core.security import hash_password, verify_password
from app.entities import User
from app.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.modules.users.repository import UserRepository

MAX_TOPUP = 50000


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def register_user(self, email, password, phone=None, role="student") -> User:
        if self.repository.get_user_by_email(email):
            raise ConflictError("Пользователь с таким email уже зарегистрирован")
        return self.repository.save_user(
            email=email, phone=phone, password_hash=hash_password(password), role=role
        )

    def authenticate(self, email, password) -> User:
        u = self.repository.get_user_by_email(email)
        if not u or not verify_password(password, u.password_hash or ""):
            raise UnauthorizedError("Неверный email или пароль")
        if u.is_blocked:
            raise ForbiddenError("Пользователь заблокирован")
        return u

    def top_up_balance(self, user_id, amount) -> float:
        u = self.repository.get_user_by_id(user_id)
        if not u:
            raise NotFoundError("Пользователь не найден")
        if u.is_blocked:
            raise ForbiddenError("Пользователь заблокирован")
        if amount > MAX_TOPUP:
            raise ValueError("Максимальная сумма пополнения — 50000 рублей")
        new_balance = u.balance + amount
        self.repository.update_user_balance(user_id, new_balance)
        return new_balance
