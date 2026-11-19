"""gRPC-микросервис доставки (Strangler Fig).

Запускается отдельным процессом:  python delivery_server.py
Слушает порт 50051. Пока использует общую PostgreSQL (см. README —
в идеальном микросервисе у delivery должна быть своя БД).
"""
import os
import sys
import time
import logging
from concurrent import futures
from datetime import datetime, timezone

import grpc

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.database import SessionLocal  # noqa: E402
from app.models import Delivery as DeliveryModel, Order as OrderModel  # noqa: E402

import delivery_pb2          # noqa: E402
import delivery_pb2_grpc     # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("delivery.grpc")

TRACK_STATUSES = [
    ("in_progress", "Курьер назначен"),
    ("on_the_way",  "Курьер в пути"),
    ("delivered",   "Доставлено"),
]


class DeliveryServiceServicer(delivery_pb2_grpc.DeliveryServiceServicer):

    # ---------- унарные методы ----------
    def AssignCourier(self, request, context):
        db = SessionLocal()
        try:
            order = db.query(OrderModel).filter(OrderModel.id == request.order_id).first()
            if not order:
                context.abort(grpc.StatusCode.NOT_FOUND, "Заказ не найден")
            if order.status != "paid":
                context.abort(grpc.StatusCode.FAILED_PRECONDITION,
                              "Курьера можно назначить только на оплаченный заказ")
            active = (db.query(DeliveryModel)
                      .filter(DeliveryModel.courier_id == request.courier_id,
                              DeliveryModel.status == "in_progress")
                      .first())
            if active:
                context.abort(grpc.StatusCode.ALREADY_EXISTS,
                              "У курьера уже есть активная доставка")
            row = DeliveryModel(order_id=request.order_id,
                                courier_id=request.courier_id,
                                status="in_progress")
            db.add(row)
            db.commit()
            db.refresh(row)
            return delivery_pb2.AssignCourierResponse(
                delivery_id=row.id, status=row.status)
        finally:
            db.close()

    def CompleteDelivery(self, request, context):
        db = SessionLocal()
        try:
            row = db.query(DeliveryModel).filter(DeliveryModel.id == request.delivery_id).first()
            if not row:
                context.abort(grpc.StatusCode.NOT_FOUND, "Доставка не найдена")
            if row.status == "completed":
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Доставка уже завершена")
            if row.status == "cancelled":
                context.abort(grpc.StatusCode.FAILED_PRECONDITION,
                              "Отменённую доставку нельзя завершить")
            row.status = "completed"
            order = db.query(OrderModel).filter(OrderModel.id == row.order_id).first()
            if order:
                order.status = "delivered"
            db.commit()
            return delivery_pb2.CompleteDeliveryResponse(status=row.status)
        finally:
            db.close()

    def GetDelivery(self, request, context):
        db = SessionLocal()
        try:
            row = db.query(DeliveryModel).filter(DeliveryModel.id == request.delivery_id).first()
            if not row:
                context.abort(grpc.StatusCode.NOT_FOUND, "Доставка не найдена")
            return self._pb(row)
        finally:
            db.close()

    def GetDeliveryByOrder(self, request, context):
        db = SessionLocal()
        try:
            row = (db.query(DeliveryModel)
                   .filter(DeliveryModel.order_id == request.order_id)
                   .order_by(DeliveryModel.id.desc())
                   .first())
            if not row:
                context.abort(grpc.StatusCode.NOT_FOUND, "Доставка не найдена")
            return self._pb(row)
        finally:
            db.close()

    def ListDeliveries(self, request, context):
        db = SessionLocal()
        try:
            rows = (db.query(DeliveryModel)
                    .filter(DeliveryModel.courier_id == request.courier_id)
                    .all())
            return delivery_pb2.ListDeliveriesResponse(
                items=[self._item(r) for r in rows])
        finally:
            db.close()

    def ListAllDeliveries(self, request, context):
        db = SessionLocal()
        try:
            rows = db.query(DeliveryModel).all()
            return delivery_pb2.ListDeliveriesResponse(
                items=[self._item(r) for r in rows])
        finally:
            db.close()

    # ---------- Server Streaming ----------
    def TrackDelivery(self, request, context):
        for status, msg in TRACK_STATUSES:
            if not context.is_active():
                return
            yield delivery_pb2.DeliveryStatusUpdate(
                delivery_id=request.delivery_id,
                status=status,
                message=msg,
                timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            )
            time.sleep(2)

    # ---------- Bidirectional Streaming ----------
    def ChatWithCourier(self, request_iterator, context):
        try:
            for msg in request_iterator:
                yield delivery_pb2.ChatMessage(
                    sender="courier",
                    text=f"Получено: {msg.text}",
                    timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                )
        except Exception:
            return

    # ---------- helpers ----------
    @staticmethod
    def _pb(row):
        return delivery_pb2.GetDeliveryResponse(
            id=row.id,
            order_id=row.order_id or 0,
            courier_id=row.courier_id or 0,
            status=row.status or "pending",
        )

    @staticmethod
    def _item(row):
        return delivery_pb2.DeliveryItem(
            id=row.id,
            order_id=row.order_id or 0,
            courier_id=row.courier_id or 0,
            status=row.status or "pending",
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    delivery_pb2_grpc.add_DeliveryServiceServicer_to_server(
        DeliveryServiceServicer(), server)
    port = int(os.getenv("DELIVERY_GRPC_PORT", "50051"))
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"Delivery gRPC Server running on port {port}")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == "__main__":
    serve()
