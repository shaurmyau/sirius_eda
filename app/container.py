"""
Точка сборки слоёв (composition root).

Единственное место, которое знает, какая реализация репозитория используется.
Для замены хранилища достаточно переключить REPO_BACKEND:
service.py и router.py при этом не меняются.

    REPO_BACKEND=postgres  (по умолчанию) - PostgreSQL через SQLAlchemy
    REPO_BACKEND=memory                    - хранение в памяти
"""
import os

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.memory_store import memory_store
from app.modules.delivery.repository import (
    InMemoryDeliveryRepository,
    SqlDeliveryRepository,
)
from app.modules.delivery.service import DeliveryService
from app.modules.menu.repository import InMemoryMenuRepository, SqlMenuRepository
from app.modules.menu.service import MenuService
from app.modules.orders.repository import (
    InMemoryOrderRepository,
    SqlOrderRepository,
)
from app.modules.orders.service import OrderService
from app.modules.users.repository import InMemoryUserRepository, SqlUserRepository
from app.modules.users.service import UserService


def use_memory_backend() -> bool:
    return os.getenv("REPO_BACKEND", "postgres").lower() == "memory"


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    if use_memory_backend():
        return UserService(InMemoryUserRepository(memory_store))
    return UserService(SqlUserRepository(db))


def get_menu_service(db: Session = Depends(get_db)) -> MenuService:
    if use_memory_backend():
        return MenuService(InMemoryMenuRepository(memory_store))
    return MenuService(SqlMenuRepository(db))


def get_order_service(db: Session = Depends(get_db)) -> OrderService:
    if use_memory_backend():
        return OrderService(InMemoryOrderRepository(memory_store))
    return OrderService(SqlOrderRepository(db))


def get_delivery_service(db: Session = Depends(get_db)) -> DeliveryService:
    if use_memory_backend():
        return DeliveryService(InMemoryDeliveryRepository(memory_store))
    return DeliveryService(SqlDeliveryRepository(db))
