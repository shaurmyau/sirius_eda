"""Инфраструктурный слой delivery."""
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.entities import Delivery, Order, User
from app.mappers import to_delivery, to_order, to_user
from app.memory_store import MemoryStore
from app.models import Delivery as DeliveryModel
from app.models import Order as OrderModel
from app.models import User as UserModel


class DeliveryRepository(ABC):
    @abstractmethod
    def get_order_by_id(self, order_id: int) -> Order | None: ...
    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None: ...
    @abstractmethod
    def get_delivery_by_id(self, delivery_id: int) -> Delivery | None: ...
    @abstractmethod
    def get_active_delivery_by_courier(self, courier_id: int) -> Delivery | None: ...
    @abstractmethod
    def save_delivery(self, order_id: int, courier_id: int) -> Delivery: ...
    @abstractmethod
    def save_completion(self, delivery: Delivery, order: Order | None) -> None: ...
    @abstractmethod
    def list_deliveries_by_courier(self, courier_id: int) -> list[Delivery]: ...
    @abstractmethod
    def list_all_deliveries(self) -> list[Delivery]: ...


class SqlDeliveryRepository(DeliveryRepository):
    def __init__(self, db: Session):
        self.db = db

    def get_order_by_id(self, order_id):
        return to_order(self.db.query(OrderModel).filter(OrderModel.id == order_id).first())

    def get_user_by_id(self, user_id):
        return to_user(self.db.query(UserModel).filter(UserModel.id == user_id).first())

    def get_delivery_by_id(self, delivery_id):
        return to_delivery(
            self.db.query(DeliveryModel).filter(DeliveryModel.id == delivery_id).first()
        )

    def get_active_delivery_by_courier(self, courier_id):
        row = (
            self.db.query(DeliveryModel)
            .filter(DeliveryModel.courier_id == courier_id,
                    DeliveryModel.status == "in_progress")
            .first()
        )
        return to_delivery(row)

    def save_delivery(self, order_id, courier_id):
        row = DeliveryModel(order_id=order_id, courier_id=courier_id, status="in_progress")
        self.db.add(row)
        order = self.db.query(OrderModel).filter(OrderModel.id == order_id).first()
        if order is not None:
            order.status = "on_the_way"
            self.db.add(order)
        self.db.commit()
        self.db.refresh(row)
        return to_delivery(row)

    def save_completion(self, delivery, order):
        drow = self.db.query(DeliveryModel).filter(DeliveryModel.id == delivery.id).first()
        drow.status = delivery.status
        self.db.add(drow)
        if order is not None:
            orow = self.db.query(OrderModel).filter(OrderModel.id == order.id).first()
            orow.status = order.status
            self.db.add(orow)
        self.db.commit()

    def list_deliveries_by_courier(self, courier_id):
        rows = self.db.query(DeliveryModel).filter(DeliveryModel.courier_id == courier_id).all()
        return [to_delivery(r) for r in rows]

    def list_all_deliveries(self):
        rows = self.db.query(DeliveryModel).all()
        return [to_delivery(r) for r in rows]


class InMemoryDeliveryRepository(DeliveryRepository):
    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    def get_order_by_id(self, order_id):
        return self.store.orders.get(order_id)

    def get_user_by_id(self, user_id):
        return self.store.users.get(user_id)

    def get_delivery_by_id(self, delivery_id):
        return self.store.deliveries.get(delivery_id)

    def get_active_delivery_by_courier(self, courier_id):
        for d in self.store.deliveries.values():
            if d.courier_id == courier_id and d.status == "in_progress":
                return d
        return None

    def save_delivery(self, order_id, courier_id):
        d = Delivery(id=self.store.next_id(self.store.deliveries),
                     order_id=order_id, courier_id=courier_id, status="in_progress")
        self.store.deliveries[d.id] = d
        order = self.store.orders.get(order_id)
        if order is not None:
            order.status = "on_the_way"
        return d

    def save_completion(self, delivery, order):
        self.store.deliveries[delivery.id] = delivery
        if order is not None:
            self.store.orders[order.id] = order

    def list_deliveries_by_courier(self, courier_id):
        return [d for d in self.store.deliveries.values() if d.courier_id == courier_id]

    def list_all_deliveries(self):
        return list(self.store.deliveries.values())
