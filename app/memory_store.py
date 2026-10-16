"""Хранилище в памяти."""
from dataclasses import dataclass

from app.entities import Delivery, MenuItem, Order, User


@dataclass
class RefreshTokenRecord:
    jti: str
    user_id: int
    token_hash: str
    expires_at: float
    is_revoked: bool = False


class MemoryStore:
    def __init__(self):
        self.users: dict[int, User] = {}
        self.menu_items: dict[int, MenuItem] = {}
        self.orders: dict[int, Order] = {}
        self.deliveries: dict[int, Delivery] = {}
        self.refresh_tokens: dict[str, RefreshTokenRecord] = {}

    @staticmethod
    def next_id(table: dict) -> int:
        return max(table, default=0) + 1

    def clear(self):
        for d in (self.users, self.menu_items, self.orders, self.deliveries, self.refresh_tokens):
            d.clear()


memory_store = MemoryStore()
