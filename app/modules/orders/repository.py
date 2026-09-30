"""
Инфраструктурный слой модуля orders (Круг 3).
Абстрактный интерфейс и две реализации: SQL и in-memory.
Класс отвечает только за ввод-вывод, бизнес-правил здесь нет.
"""
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.entities import MenuItem, Order, User
from app.mappers import to_menu_item, to_user
from app.memory_store import MemoryStore
from app.models import MenuItem as MenuItemModel
from app.models import Order as OrderModel
from app.models import User as UserModel


class OrderRepository(ABC):
    """Интерфейс доступа к данным, нужным сценарию оформления заказа."""

    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None:
        """Извлечение пользователя по идентификатору."""

    @abstractmethod
    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None:
        """Извлечение блюда из меню по идентификатору."""

    @abstractmethod
    def save_order_and_update_balance(
        self, user_id: int, item_id: int, quantity: int, new_balance: float
    ) -> int:
        """
        Создаёт заказ и сохраняет новый баланс пользователя одной транзакцией.
        Возвращает идентификатор созданного заказа.
        """


class SqlOrderRepository(OrderRepository):
    """Реализация на PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: int) -> User | None:
        row = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        return to_user(row)

    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None:
        row = self.db.query(MenuItemModel).filter(MenuItemModel.id == item_id).first()
        return to_menu_item(row)

    def save_order_and_update_balance(
        self, user_id: int, item_id: int, quantity: int, new_balance: float
    ) -> int:
        user_row = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        user_row.balance = new_balance
        self.db.add(user_row)

        new_order = OrderModel(
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            status="processing",
        )
        self.db.add(new_order)

        self.db.commit()  # UPDATE баланса и INSERT заказа - одна транзакция
        self.db.refresh(new_order)
        return new_order.id


class InMemoryOrderRepository(OrderRepository):
    """Реализация в памяти (для тестов и запуска без СУБД)."""

    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.store.users.get(user_id)

    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None:
        return self.store.menu_items.get(item_id)

    def save_order_and_update_balance(
        self, user_id: int, item_id: int, quantity: int, new_balance: float
    ) -> int:
        self.store.users[user_id].balance = new_balance
        order = Order(
            id=self.store.next_id(self.store.orders),
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            status="processing",
        )
        self.store.orders[order.id] = order
        return order.id
