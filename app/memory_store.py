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
        self.promo_codes: dict[str, dict] = {}
        self.promo_usages: set[tuple[str, int]] = set()
        self.loyalty_accounts: dict[int, dict] = {}
        self.loyalty_transactions: dict[str, dict] = {}

    @staticmethod
    def next_id(table: dict) -> int:
        return max(table, default=0) + 1

    def clear(self):
        for d in (self.users, self.menu_items, self.orders, self.deliveries, self.refresh_tokens,
                 self.promo_codes, self.loyalty_accounts, self.loyalty_transactions):
            d.clear()
        self.promo_usages.clear()


memory_store = MemoryStore()
