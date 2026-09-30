"""
Инфраструктурный слой модуля users (Круг 3).
Абстрактный интерфейс и две реализации: SQL и in-memory.
Бизнес-правил здесь нет.
"""
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.entities import User
from app.mappers import to_user
from app.memory_store import MemoryStore
from app.models import User as UserModel


class UserRepository(ABC):
    """Интерфейс доступа к данным пользователей."""

    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None: ...

    @abstractmethod
    def get_user_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    def save_user(self, email: str, phone: str | None) -> User:
        """Создаёт пользователя с нулевым балансом."""

    @abstractmethod
    def update_user_balance(self, user_id: int, new_balance: float) -> None: ...


class SqlUserRepository(UserRepository):
    """Реализация на PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: int) -> User | None:
        row = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        return to_user(row)

    def get_user_by_email(self, email: str) -> User | None:
        row = self.db.query(UserModel).filter(UserModel.email == email).first()
        return to_user(row)

    def save_user(self, email: str, phone: str | None) -> User:
        row = UserModel(email=email, phone=phone, balance=0.0, is_blocked=False)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return to_user(row)

    def update_user_balance(self, user_id: int, new_balance: float) -> None:
        row = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        row.balance = new_balance
        self.db.add(row)
        self.db.commit()


class InMemoryUserRepository(UserRepository):
    """Реализация в памяти (для тестов и запуска без СУБД)."""

    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.store.users.get(user_id)

    def get_user_by_email(self, email: str) -> User | None:
        for user in self.store.users.values():
            if user.email == email:
                return user
        return None

    def save_user(self, email: str, phone: str | None) -> User:
        user = User(
            id=self.store.next_id(self.store.users),
            email=email,
            phone=phone,
            balance=0.0,
            is_blocked=False,
        )
        self.store.users[user.id] = user
        return user

    def update_user_balance(self, user_id: int, new_balance: float) -> None:
        self.store.users[user_id].balance = new_balance
