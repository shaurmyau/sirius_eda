"""
Хранилище в памяти для InMemory-репозиториев (тесты и запуск без PostgreSQL).
Общее для всех модулей, чтобы orders видел пользователей и блюда.
"""
from app.entities import Delivery, MenuItem, Order, User


class MemoryStore:
    def __init__(self):
        self.users: dict[int, User] = {}
        self.menu_items: dict[int, MenuItem] = {}
        self.orders: dict[int, Order] = {}
        self.deliveries: dict[int, Delivery] = {}

    @staticmethod
    def next_id(table: dict) -> int:
        return max(table, default=0) + 1

    def clear(self) -> None:
        self.users.clear()
        self.menu_items.clear()
        self.orders.clear()
        self.deliveries.clear()


# Общий экземпляр для приложения (REPO_BACKEND=memory)
memory_store = MemoryStore()
