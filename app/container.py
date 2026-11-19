"""Точка сборки слоёв (composition root)."""
import os

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.memory_store import memory_store
from app.modules.auth.repository import InMemoryAuthRepository, SqlAuthRepository
from app.modules.auth.service import AuthService
from app.modules.delivery.repository import InMemoryDeliveryRepository, SqlDeliveryRepository
from app.modules.delivery.grpc_repository import GrpcDeliveryRepository
from app.modules.delivery.grpc_client import DeliveryGrpcClient
from app.modules.delivery.service import DeliveryService
from app.modules.menu.repository import InMemoryMenuRepository, SqlMenuRepository
from app.modules.menu.service import MenuService
from app.modules.orders.repository import InMemoryOrderRepository, SqlOrderRepository
from app.modules.orders.service import OrderService
from app.modules.users.repository import InMemoryUserRepository, SqlUserRepository
from app.modules.users.service import UserService


def use_memory_backend() -> bool:
    return (settings.REPO_BACKEND or "postgres").lower() == "memory"


def use_grpc_delivery() -> bool:
    """Идём ли в gRPC-микросервис delivery (Strangler Fig).

    По умолчанию — да. Отключить: DELIVERY_BACKEND=sql.
    """
    backend = (settings.DELIVERY_BACKEND or "grpc").lower()
    return backend == "grpc" and not use_memory_backend()


def get_event_publisher():
    """Публикатор событий в RabbitMQ (Практическая работа № 7).

    В memory-режиме (тесты) событий нет — возвращаем None.
    Импорт ленивый: aio_pika не нужен, пока события не публикуются.
    """
    if use_memory_backend():
        return None
    from app.core.rabbitmq import publish_event_sync
    return publish_event_sync


def get_user_repository(db: Session = Depends(get_db)):
    return InMemoryUserRepository(memory_store) if use_memory_backend() else SqlUserRepository(db)


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(get_user_repository(db))


def get_menu_service(db: Session = Depends(get_db)) -> MenuService:
    return MenuService(InMemoryMenuRepository(memory_store) if use_memory_backend() else SqlMenuRepository(db))


def get_order_service(db: Session = Depends(get_db)) -> OrderService:
    return OrderService(
        InMemoryOrderRepository(memory_store) if use_memory_backend() else SqlOrderRepository(db),
        publisher=get_event_publisher(),
    )


def get_delivery_service(db: Session = Depends(get_db)) -> DeliveryService:
    if use_memory_backend():
        repo = InMemoryDeliveryRepository(memory_store)
    elif use_grpc_delivery():
        repo = GrpcDeliveryRepository(db, DeliveryGrpcClient())
    else:
        repo = SqlDeliveryRepository(db)
    return DeliveryService(repo)


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(InMemoryAuthRepository(memory_store) if use_memory_backend() else SqlAuthRepository(db))
