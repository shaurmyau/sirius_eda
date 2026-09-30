"""
Unit-тесты слоя бизнес-логики. Не требуют PostgreSQL и веб-сервера:
сервисы работают с in-memory репозиториями.
"""
import pytest

from app.entities import Delivery, MenuItem, Order, User
from app.exceptions import ForbiddenError, NotFoundError
from app.memory_store import MemoryStore
from app.modules.delivery.repository import InMemoryDeliveryRepository
from app.modules.delivery.service import DeliveryService
from app.modules.menu.repository import InMemoryMenuRepository
from app.modules.menu.service import MenuService
from app.modules.orders.repository import InMemoryOrderRepository
from app.modules.orders.service import OrderService
from app.modules.users.repository import InMemoryUserRepository
from app.modules.users.service import UserService


@pytest.fixture
def store():
    s = MemoryStore()
    s.users[1] = User(1, "student@sirius.ru", None, 100.0, False)
    s.users[2] = User(2, "courier@sirius.ru", None, 0.0, False)
    s.users[3] = User(3, "blocked@sirius.ru", None, 0.0, True)
    s.menu_items[1] = MenuItem(1, "Борщ", 30.0, True)
    s.menu_items[2] = MenuItem(2, "Пицца", 50.0, False)
    return s


# ---------------------------- orders ----------------------------------------
def test_create_order_success(store):
    service = OrderService(InMemoryOrderRepository(store))

    order_id = service.create_order(user_id=1, item_id=1, quantity=2)

    assert order_id == 1
    assert store.users[1].balance == 40.0
    assert store.orders[1].status == "processing"


def test_create_order_not_enough_money(store):
    service = OrderService(InMemoryOrderRepository(store))

    with pytest.raises(ValueError, match="Недостаточно средств"):
        service.create_order(user_id=1, item_id=1, quantity=4)

    assert store.users[1].balance == 100.0
    assert store.orders == {}


def test_create_order_unknown_user(store):
    service = OrderService(InMemoryOrderRepository(store))

    with pytest.raises(NotFoundError):
        service.create_order(user_id=99, item_id=1, quantity=1)


def test_create_order_item_unavailable(store):
    service = OrderService(InMemoryOrderRepository(store))

    with pytest.raises(ValueError, match="недоступно"):
        service.create_order(user_id=1, item_id=2, quantity=1)


# ---------------------------- users -----------------------------------------
def test_register_user_success_and_duplicate(store):
    service = UserService(InMemoryUserRepository(store))

    user = service.register_user("new@sirius.ru", "1234567890")
    assert user.id == 4
    assert user.balance == 0.0

    with pytest.raises(ValueError, match="уже зарегистрирован"):
        service.register_user("new@sirius.ru", None)


def test_top_up_balance(store):
    service = UserService(InMemoryUserRepository(store))

    assert service.top_up_balance(1, 50) == 150.0
    assert store.users[1].balance == 150.0


def test_top_up_blocked_user(store):
    service = UserService(InMemoryUserRepository(store))

    with pytest.raises(ForbiddenError):
        service.top_up_balance(3, 10)


def test_top_up_limit_exceeded(store):
    service = UserService(InMemoryUserRepository(store))

    with pytest.raises(ValueError, match="50000"):
        service.top_up_balance(1, 50001)


# ---------------------------- menu ------------------------------------------
def test_create_menu_item_and_duplicate(store):
    service = MenuService(InMemoryMenuRepository(store))

    assert service.create_menu_item("Суп", 25.0) == 3
    with pytest.raises(ValueError, match="уже существует"):
        service.create_menu_item("Суп", 30.0)


def test_update_menu_item(store):
    service = MenuService(InMemoryMenuRepository(store))

    service.update_menu_item(1, name=None, price=35.0, is_available=False)

    assert store.menu_items[1].price == 35.0
    assert store.menu_items[1].name == "Борщ"
    assert store.menu_items[1].is_available is False


def test_update_unknown_menu_item(store):
    service = MenuService(InMemoryMenuRepository(store))

    with pytest.raises(NotFoundError):
        service.update_menu_item(99, name="X", price=None, is_available=None)


# ---------------------------- delivery --------------------------------------
def test_assign_courier_requires_paid_order(store):
    store.orders[1] = Order(1, 1, 1, 1, "processing")
    service = DeliveryService(InMemoryDeliveryRepository(store))

    with pytest.raises(ValueError, match="оплаченный"):
        service.assign_courier(order_id=1, courier_id=2)


def test_assign_courier_rules(store):
    store.orders[1] = Order(1, 1, 1, 1, "paid")
    store.orders[2] = Order(2, 1, 1, 1, "paid")
    service = DeliveryService(InMemoryDeliveryRepository(store))

    with pytest.raises(ForbiddenError):
        service.assign_courier(order_id=1, courier_id=3)

    assert service.assign_courier(order_id=1, courier_id=2) == 1
    with pytest.raises(ValueError, match="активная доставка"):
        service.assign_courier(order_id=2, courier_id=2)


def test_complete_delivery_updates_order(store):
    store.orders[1] = Order(1, 1, 1, 1, "paid")
    store.deliveries[1] = Delivery(1, 1, 2, "in_progress")
    service = DeliveryService(InMemoryDeliveryRepository(store))

    service.complete_delivery(1)

    assert store.deliveries[1].status == "completed"
    assert store.orders[1].status == "delivered"
    with pytest.raises(ValueError, match="уже завершена"):
        service.complete_delivery(1)
