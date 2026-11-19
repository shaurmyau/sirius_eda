"""gRPC-клиент для микросервиса доставки.

Инфраструктурный адаптер между бизнес-логикой монолита и сетью.
Ошибки gRPC транслируются в доменные исключения / стандартные исключения
Python, которые роутер уже умеет превращать в HTTP-статусы.
"""
import logging
import os
import sys
from typing import Iterator

import grpc

# Защита: если cwd не в sys.path (например, запуск из другого каталога),
# сгенерированные pb2-модули лежат в корне проекта.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import delivery_pb2          # noqa: E402
import delivery_pb2_grpc     # noqa: E402

from app.core.config import settings  # noqa: E402

log = logging.getLogger(__name__)


class DeliveryGrpcClient:
    def __init__(self, host: str | None = None, port: int | None = None,
                 timeout: float | None = None):
        self.host    = host    or settings.DELIVERY_GRPC_HOST
        self.port    = port    or settings.DELIVERY_GRPC_PORT
        self.timeout = timeout or settings.DELIVERY_GRPC_TIMEOUT
        self.channel = grpc.insecure_channel(f"{self.host}:{self.port}")
        self.stub    = delivery_pb2_grpc.DeliveryServiceStub(self.channel)

    # ---------- unary ----------
    def assign_courier(self, order_id: int, courier_id: int) -> dict:
        try:
            req = delivery_pb2.AssignCourierRequest(
                order_id=order_id, courier_id=courier_id)
            resp = self.stub.AssignCourier(req, timeout=self.timeout)
            return {"delivery_id": resp.delivery_id, "status": resp.status}
        except grpc.RpcError as e:
            self._handle_error(e)

    def complete_delivery(self, delivery_id: int) -> dict:
        try:
            req = delivery_pb2.CompleteDeliveryRequest(delivery_id=delivery_id)
            resp = self.stub.CompleteDelivery(req, timeout=self.timeout)
            return {"status": resp.status}
        except grpc.RpcError as e:
            self._handle_error(e)

    def get_delivery(self, delivery_id: int) -> dict | None:
        try:
            req = delivery_pb2.GetDeliveryRequest(delivery_id=delivery_id)
            resp = self.stub.GetDelivery(req, timeout=self.timeout)
            return self._resp_to_dict(resp)
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                return None
            self._handle_error(e)

    def get_delivery_by_order(self, order_id: int) -> dict | None:
        try:
            req = delivery_pb2.GetDeliveryByOrderRequest(order_id=order_id)
            resp = self.stub.GetDeliveryByOrder(req, timeout=self.timeout)
            return self._resp_to_dict(resp)
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                return None
            self._handle_error(e)

    def list_deliveries(self, courier_id: int) -> list[dict]:
        try:
            req = delivery_pb2.ListDeliveriesRequest(courier_id=courier_id)
            resp = self.stub.ListDeliveries(req, timeout=self.timeout)
            return [self._item_to_dict(i) for i in resp.items]
        except grpc.RpcError as e:
            self._handle_error(e)

    def list_all_deliveries(self) -> list[dict]:
        try:
            req = delivery_pb2.Empty()
            resp = self.stub.ListAllDeliveries(req, timeout=self.timeout)
            return [self._item_to_dict(i) for i in resp.items]
        except grpc.RpcError as e:
            self._handle_error(e)

    # ---------- server streaming ----------
    def track_delivery(self, delivery_id: int) -> Iterator[dict]:
        req = delivery_pb2.TrackDeliveryRequest(delivery_id=delivery_id)
        try:
            for upd in self.stub.TrackDelivery(req, timeout=self.timeout * 10):
                yield {
                    "delivery_id": upd.delivery_id,
                    "status":      upd.status,
                    "message":     upd.message,
                    "timestamp_ms": upd.timestamp_ms,
                }
        except grpc.RpcError as e:
            self._handle_error(e)

    # ---------- bidirectional streaming ----------
    def chat_with_courier(self, messages: Iterator[str],
                          sender: str = "student") -> Iterator[dict]:
        def gen():
            for text in messages:
                yield delivery_pb2.ChatMessage(
                    sender=sender, text=text,
                    timestamp_ms=0)

        try:
            for resp in self.stub.ChatWithCourier(gen(), timeout=self.timeout * 10):
                yield {
                    "sender":       resp.sender,
                    "text":         resp.text,
                    "timestamp_ms": resp.timestamp_ms,
                }
        except grpc.RpcError as e:
            self._handle_error(e)

    # ---------- helpers ----------
    @staticmethod
    def _resp_to_dict(resp) -> dict:
        return {
            "id":         resp.id,
            "order_id":   resp.order_id,
            "courier_id": resp.courier_id,
            "status":     resp.status,
        }

    @staticmethod
    def _item_to_dict(item) -> dict:
        return {
            "id":         item.id,
            "order_id":   item.order_id,
            "courier_id": item.courier_id,
            "status":     item.status,
        }

    def _handle_error(self, e: grpc.RpcError):
        code   = e.code()
        detail = (e.details() or "").strip()
        if code == grpc.StatusCode.NOT_FOUND:
            raise ValueError(detail or "Объект не найден")
        if code == grpc.StatusCode.UNAVAILABLE:
            raise ConnectionError("Delivery service is unavailable")
        if code == grpc.StatusCode.DEADLINE_EXCEEDED:
            raise TimeoutError("Delivery service timeout")
        if code == grpc.StatusCode.FAILED_PRECONDITION:
            raise ValueError(detail or "Недопустимое состояние")
        if code == grpc.StatusCode.ALREADY_EXISTS:
            raise ValueError(detail or "Объект уже существует")
        raise RuntimeError(f"gRPC error [{code}]: {detail}")
