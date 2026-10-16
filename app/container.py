"""Точка сборки слоёв (composition root)."""
import os

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.memory_store import memory_store
from app.modules.auth.repository import InMemoryAuthRepository, SqlAuthRepository
from app.modules.auth.service import AuthService
from app.modules.delivery.repository import InMemoryDeliveryRepository, SqlDeliveryRepository
from app.modules.delivery.service import DeliveryService
from app.modules.menu.repository import InMemoryMenuRepository, SqlMenuRepository
from app.modules.menu.service import MenuService
from app.modules.orders.repository import InMemoryOrderRepository, SqlOrderRepository
from app.modules.orders.service import OrderService
from app.modules.users.repository import InMemoryUserRepository, SqlUserRepository
from app.modules.users.service import UserService


def use_memory_backend() -> bool:
    return os.getenv("REPO_BACKEND", "postgres").lower() == "memory"


def get_user_repository(db: Session = Depends(get_db)):
    return InMemoryUserRepository(memory_store) if use_memory_backend() else SqlUserRepository(db)


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(get_user_repository(db))


def get_menu_service(db: Session = Depends(get_db)) -> MenuService:
    return MenuService(InMemoryMenuRepository(memory_store) if use_memory_backend() else SqlMenuRepository(db))


def get_order_service(db: Session = Depends(get_db)) -> OrderService:
    return OrderService(InMemoryOrderRepository(memory_store) if use_memory_backend() else SqlOrderRepository(db))


def get_delivery_service(db: Session = Depends(get_db)) -> DeliveryService:
    return DeliveryService(InMemoryDeliveryRepository(memory_store) if use_memory_backend() else SqlDeliveryRepository(db))


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(InMemoryAuthRepository(memory_store) if use_memory_backend() else SqlAuthRepository(db))
