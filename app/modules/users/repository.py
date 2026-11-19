"""Repository модуля users."""
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.entities import User
from app.mappers import to_user
from app.memory_store import MemoryStore
from app.permissions import permissions_for_role
from app.models import Role as RoleModel
from app.models import User as UserModel


class UserRepository(ABC):
    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None: ...
    @abstractmethod
    def get_user_by_email(self, email: str) -> User | None: ...
    @abstractmethod
    def save_user(self, email, phone, password_hash=None, role="student") -> User: ...
    @abstractmethod
    def update_user_balance(self, user_id: int, new_balance: float) -> None: ...


class SqlUserRepository(UserRepository):
    def __init__(self, db: Session):
        self.db = db

    def _ensure_role(self, name):
        role = self.db.query(RoleModel).filter(RoleModel.name == name).first()
        if not role:
            role = RoleModel(name=name)
            self.db.add(role)
            self.db.flush()
        return role

    def get_user_by_id(self, user_id):
        return to_user(self.db.query(UserModel).filter(UserModel.id == user_id).first())

    def get_user_by_email(self, email):
        return to_user(self.db.query(UserModel).filter(UserModel.email == email).first())

    def save_user(self, email, phone, password_hash=None, role="student"):
        role_row = self._ensure_role(role)
        row = UserModel(email=email, phone=phone, balance=0.0, is_blocked=False,
                        password_hash=password_hash, role_id=role_row.id)
        self.db.add(row); self.db.commit(); self.db.refresh(row)
        return to_user(row)

    def update_user_balance(self, user_id, new_balance):
        row = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        row.balance = new_balance; self.db.add(row); self.db.commit()


class InMemoryUserRepository(UserRepository):
    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    def get_user_by_id(self, user_id):
        return self.store.users.get(user_id)

    def get_user_by_email(self, email):
        for u in self.store.users.values():
            if u.email == email:
                return u
        return None

    def save_user(self, email, phone, password_hash=None, role="student"):
        u = User(
            id=self.store.next_id(self.store.users),
            email=email, phone=phone, balance=0.0, is_blocked=False,
            role=role, password_hash=password_hash,
            permissions=frozenset(permissions_for_role(role)),
        )
        self.store.users[u.id] = u
        return u

    def update_user_balance(self, user_id, new_balance):
        self.store.users[user_id].balance = new_balance
