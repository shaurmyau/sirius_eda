"""DeliveryRepository поверх gRPC-микросервиса.

Доставки теперь живут в gRPC-сервисе; заказы и пользователи остаются
в БД монолита (его домен), поэтому читаем их напрямую.

Это позволяет соблюсти паттерн Strangler Fig: интерфейс DeliveryRepository
не меняется, а реализация подменяется в container.py.
"""
from sqlalchemy.orm import Session

from app.entities import Delivery, Order, User
from app.mappers import to_order, to_user
from app.models import Order as OrderModel
from app.models import User as UserModel
from app.modules.delivery.grpc_client import DeliveryGrpcClient
from app.modules.delivery.repository import DeliveryRepository


def _to_entity(d: dict | None) -> Delivery | None:
    if d is None:
        return None
    return Delivery(
        id=d["id"],
        order_id=d["order_id"],
        courier_id=d.get("courier_id") or None,
        status=d["status"],
    )


class GrpcDeliveryRepository(DeliveryRepository):

    def __init__(self, db: Session, client: DeliveryGrpcClient | None = None):
        self.db = db
        self.client = client or DeliveryGrpcClient()

    # ---- orders / users — своя БД монолита ----
    def get_order_by_id(self, order_id: int) -> Order | None:
        row = self.db.query(OrderModel).filter(OrderModel.id == order_id).first()
        return to_order(row)

    def get_user_by_id(self, user_id: int) -> User | None:
        row = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        return to_user(row)

    # ---- deliveries — через gRPC ----
    def get_delivery_by_id(self, delivery_id: int) -> Delivery | None:
        return _to_entity(self.client.get_delivery(delivery_id))

    def get_active_delivery_by_courier(self, courier_id: int) -> Delivery | None:
        for item in self.client.list_deliveries(courier_id):
            if item["status"] == "in_progress":
                return _to_entity(item)
        return None

    def save_delivery(self, order_id: int, courier_id: int) -> Delivery:
        result = self.client.assign_courier(order_id, courier_id)
        return Delivery(
            id=result["delivery_id"],
            order_id=order_id,
            courier_id=courier_id,
            status=result["status"],
        )

    def save_completion(self, delivery: Delivery, order: Order | None) -> None:
        self.client.complete_delivery(delivery.id)

    def list_deliveries_by_courier(self, courier_id: int) -> list[Delivery]:
        items = self.client.list_deliveries(courier_id)
        return [d for d in (_to_entity(i) for i in items) if d is not None]

    def list_all_deliveries(self) -> list[Delivery]:
        items = self.client.list_all_deliveries()
        return [d for d in (_to_entity(i) for i in items) if d is not None]
