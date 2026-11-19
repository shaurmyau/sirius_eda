"""Инфраструктурный слой orders."""
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.entities import MenuItem, Order, User
from app.mappers import to_menu_item, to_order, to_user
from app.memory_store import MemoryStore
from app.models import MenuItem as MenuItemModel
from app.models import Order as OrderModel
from app.models import User as UserModel


class OrderRepository(ABC):
    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None: ...
    @abstractmethod
    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None: ...
    @abstractmethod
    def save_order_and_update_balance(
        self, user_id: int, item_id: int, quantity: int, new_balance: float
    ) -> int: ...
    @abstractmethod
    def get_order_by_id(self, order_id: int) -> Order | None: ...
    @abstractmethod
    def update_order_status(self, order_id: int, status: str) -> None: ...
    @abstractmethod
    def list_orders_by_user(self, user_id: int) -> list[Order]: ...


class SqlOrderRepository(OrderRepository):
    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id):
        return to_user(self.db.query(UserModel).filter(UserModel.id == user_id).first())

    def get_menu_item_by_id(self, item_id):
        return to_menu_item(
            self.db.query(MenuItemModel).filter(MenuItemModel.id == item_id).first()
        )

    def save_order_and_update_balance(self, user_id, item_id, quantity, new_balance):
        ur = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        ur.balance = new_balance
        self.db.add(ur)
        o = OrderModel(user_id=user_id, item_id=item_id, quantity=quantity, status="processing")
        self.db.add(o)
        self.db.commit()
        self.db.refresh(o)
        return o.id

    def get_order_by_id(self, order_id):
        return to_order(self.db.query(OrderModel).filter(OrderModel.id == order_id).first())

    def update_order_status(self, order_id, status):
        row = self.db.query(OrderModel).filter(OrderModel.id == order_id).first()
        if row:
            row.status = status
            self.db.add(row)
            self.db.commit()

    def list_orders_by_user(self, user_id):
        rows = self.db.query(OrderModel).filter(OrderModel.user_id == user_id).all()
        return [to_order(r) for r in rows]


class InMemoryOrderRepository(OrderRepository):
    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    def get_user_by_id(self, user_id):
        return self.store.users.get(user_id)

    def get_menu_item_by_id(self, item_id):
        return self.store.menu_items.get(item_id)

    def save_order_and_update_balance(self, user_id, item_id, quantity, new_balance):
        self.store.users[user_id].balance = new_balance
        o = Order(
            id=self.store.next_id(self.store.orders),
            user_id=user_id, item_id=item_id, quantity=quantity, status="processing",
        )
        self.store.orders[o.id] = o
        return o.id

    def get_order_by_id(self, order_id):
        return self.store.orders.get(order_id)

    def update_order_status(self, order_id, status):
        if order_id in self.store.orders:
            self.store.orders[order_id].status = status

    def list_orders_by_user(self, user_id):
        return [o for o in self.store.orders.values() if o.user_id == user_id]
