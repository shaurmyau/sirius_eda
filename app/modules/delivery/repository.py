"""
Инфраструктурный слой модуля delivery (Круг 3).
Абстрактный интерфейс и две реализации: SQL и in-memory.
"""
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.entities import Delivery, Order, User
from app.mappers import to_delivery, to_order, to_user
from app.memory_store import MemoryStore
from app.models import Delivery as DeliveryModel
from app.models import Order as OrderModel
from app.models import User as UserModel


class DeliveryRepository(ABC):
    """Интерфейс доступа к данным доставки."""

    @abstractmethod
    def get_order_by_id(self, order_id: int) -> Order | None: ...

    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None: ...

    @abstractmethod
    def get_delivery_by_id(self, delivery_id: int) -> Delivery | None: ...

    @abstractmethod
    def get_active_delivery_by_courier(self, courier_id: int) -> Delivery | None:
        """Доставка курьера со статусом in_progress (если есть)."""

    @abstractmethod
    def save_delivery(self, order_id: int, courier_id: int) -> Delivery:
        """Создаёт доставку со статусом in_progress."""

    @abstractmethod
    def save_completion(self, delivery: Delivery, order: Order | None) -> None:
        """Сохраняет статус доставки и (если есть) заказа одной транзакцией."""


class SqlDeliveryRepository(DeliveryRepository):
    """Реализация на PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_order_by_id(self, order_id: int) -> Order | None:
        row = self.db.query(OrderModel).filter(OrderModel.id == order_id).first()
        return to_order(row)

    def get_user_by_id(self, user_id: int) -> User | None:
        row = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        return to_user(row)

    def get_delivery_by_id(self, delivery_id: int) -> Delivery | None:
        row = self.db.query(DeliveryModel).filter(DeliveryModel.id == delivery_id).first()
        return to_delivery(row)

    def get_active_delivery_by_courier(self, courier_id: int) -> Delivery | None:
        row = (
            self.db.query(DeliveryModel)
            .filter(
                DeliveryModel.courier_id == courier_id,
                DeliveryModel.status == "in_progress",
            )
            .first()
        )
        return to_delivery(row)

    def save_delivery(self, order_id: int, courier_id: int) -> Delivery:
        row = DeliveryModel(order_id=order_id, courier_id=courier_id, status="in_progress")
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return to_delivery(row)

    def save_completion(self, delivery: Delivery, order: Order | None) -> None:
        delivery_row = (
            self.db.query(DeliveryModel).filter(DeliveryModel.id == delivery.id).first()
        )
        delivery_row.status = delivery.status
        self.db.add(delivery_row)

        if order is not None:
            order_row = self.db.query(OrderModel).filter(OrderModel.id == order.id).first()
            order_row.status = order.status
            self.db.add(order_row)

        self.db.commit()


class InMemoryDeliveryRepository(DeliveryRepository):
    """Реализация в памяти (для тестов и запуска без СУБД)."""

    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    def get_order_by_id(self, order_id: int) -> Order | None:
        return self.store.orders.get(order_id)

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.store.users.get(user_id)

    def get_delivery_by_id(self, delivery_id: int) -> Delivery | None:
        return self.store.deliveries.get(delivery_id)

    def get_active_delivery_by_courier(self, courier_id: int) -> Delivery | None:
        for delivery in self.store.deliveries.values():
            if delivery.courier_id == courier_id and delivery.status == "in_progress":
                return delivery
        return None

    def save_delivery(self, order_id: int, courier_id: int) -> Delivery:
        delivery = Delivery(
            id=self.store.next_id(self.store.deliveries),
            order_id=order_id,
            courier_id=courier_id,
            status="in_progress",
        )
        self.store.deliveries[delivery.id] = delivery
        return delivery

    def save_completion(self, delivery: Delivery, order: Order | None) -> None:
        self.store.deliveries[delivery.id] = delivery
        if order is not None:
            self.store.orders[order.id] = order
