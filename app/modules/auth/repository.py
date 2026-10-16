"""Repository auth: хранение refresh-токенов."""
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.entities import User
from app.mappers import to_user
from app.memory_store import MemoryStore, RefreshTokenRecord
from app.models import RefreshToken as RefreshTokenModel
from app.models import User as UserModel


def _hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


class AuthRepository(ABC):
    @abstractmethod
    def get_user_by_email(self, email: str) -> User | None: ...
    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None: ...
    @abstractmethod
    def save_refresh_token(self, user_id, jti, token, expires_at) -> None: ...
    @abstractmethod
    def is_refresh_token_revoked(self, jti: str) -> bool: ...
    @abstractmethod
    def is_refresh_token_valid(self, jti: str, token: str) -> bool: ...
    @abstractmethod
    def revoke_refresh_token(self, jti: str) -> None: ...
    @abstractmethod
    def revoke_all_user_tokens(self, user_id: int) -> None: ...


class SqlAuthRepository(AuthRepository):
    def __init__(self, db: Session):
        self.db = db

    def get_user_by_email(self, email):
        return to_user(self.db.query(UserModel).filter(UserModel.email == email).first())

    def get_user_by_id(self, user_id):
        return to_user(self.db.query(UserModel).filter(UserModel.id == user_id).first())

    def save_refresh_token(self, user_id, jti, token, expires_at):
        self.db.add(RefreshTokenModel(user_id=user_id, jti=jti, token_hash=_hash(token),
                                      expires_at=expires_at, is_revoked=False))
        self.db.commit()

    def is_refresh_token_revoked(self, jti):
        r = self.db.query(RefreshTokenModel).filter(RefreshTokenModel.jti == jti).first()
        return bool(r and r.is_revoked)

    def is_refresh_token_valid(self, jti, token):
        r = self.db.query(RefreshTokenModel).filter(RefreshTokenModel.jti == jti).first()
        if not r or r.is_revoked: return False
        if r.token_hash != _hash(token): return False
        exp = r.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp >= datetime.now(timezone.utc)

    def revoke_refresh_token(self, jti):
        r = self.db.query(RefreshTokenModel).filter(RefreshTokenModel.jti == jti).first()
        if r: r.is_revoked = True; self.db.add(r); self.db.commit()

    def revoke_all_user_tokens(self, user_id):
        for r in self.db.query(RefreshTokenModel).filter(RefreshTokenModel.user_id == user_id).all():
            r.is_revoked = True; self.db.add(r)
        self.db.commit()


class InMemoryAuthRepository(AuthRepository):
    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    def get_user_by_email(self, email):
        for u in self.store.users.values():
            if u.email == email: return u
        return None

    def get_user_by_id(self, user_id): return self.store.users.get(user_id)

    def save_refresh_token(self, user_id, jti, token, expires_at):
        self.store.refresh_tokens[jti] = RefreshTokenRecord(
            jti=jti, user_id=user_id, token_hash=_hash(token),
            expires_at=expires_at.timestamp())

    def is_refresh_token_revoked(self, jti):
        r = self.store.refresh_tokens.get(jti)
        return bool(r and r.is_revoked)

    def is_refresh_token_valid(self, jti, token):
        r = self.store.refresh_tokens.get(jti)
        if not r or r.is_revoked: return False
        if r.token_hash != _hash(token): return False
        return r.expires_at >= datetime.now(timezone.utc).timestamp()

    def revoke_refresh_token(self, jti):
        r = self.store.refresh_tokens.get(jti)
        if r: r.is_revoked = True

    def revoke_all_user_tokens(self, user_id):
        for r in self.store.refresh_tokens.values():
            if r.user_id == user_id: r.is_revoked = True
