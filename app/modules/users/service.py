"""
Слой бизнес-логики модуля users (Круги 1 и 2).
Не зависит от fastapi и sqlalchemy.
"""
from app.entities import User
from app.exceptions import ForbiddenError, NotFoundError
from app.modules.users.repository import UserRepository

MAX_TOPUP_AMOUNT = 50000


class UserService:
    """Бизнес-правила работы с пользователями."""

    def __init__(self, repository: UserRepository):
        # Внедрение зависимости через конструктор (инверсия зависимостей).
        self.repository = repository

    def register_user(self, email: str, phone: str | None) -> User:
        """Регистрирует пользователя. ValueError, если email уже занят."""
        if self.repository.get_user_by_email(email):
            raise ValueError("Пользователь с таким email уже зарегистрирован")
        return self.repository.save_user(email, phone)

    def top_up_balance(self, user_id: int, amount: float) -> float:
        """Пополняет баланс и возвращает новый баланс."""
        user = self.repository.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("Пользователь не найден")
        if user.is_blocked:
            raise ForbiddenError("Пользователь заблокирован. Пополнение невозможно")
        if amount > MAX_TOPUP_AMOUNT:
            raise ValueError("Максимальная сумма пополнения — 50000 рублей")

        new_balance = user.balance + amount
        self.repository.update_user_balance(user_id, new_balance)
        return new_balance
