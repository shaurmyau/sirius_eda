"""Unit-тесты сервисов (in-memory)."""
import pytest

from app.entities import Delivery, MenuItem, Order, User
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
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
    s.users[1] = User(1, "student@sirius.ru", None, 100.0, False, "student")
    s.users[2] = User(2, "courier@sirius.ru", None, 0.0, False, "courier")
    s.users[3] = User(3, "blocked@sirius.ru", None, 0.0, True, "student")
    s.users[4] = User(4, "admin@sirius.ru", None, 0.0, False, "admin")
    s.menu_items[1] = MenuItem(1, "Борщ", 30.0, True)
    s.menu_items[2] = MenuItem(2, "Пицца", 50.0, False)
    return s


def test_create_order_success(store):
    srv = OrderService(InMemoryOrderRepository(store))
    assert srv.create_order(1, 1, 2) == 1
    assert store.users[1].balance == 40.0
    assert store.orders[1].status == "processing"


def test_create_order_no_money(store):
    srv = OrderService(InMemoryOrderRepository(store))
    with pytest.raises(ValueError, match="Недостаточно средств"):
        srv.create_order(1, 1, 4)


def test_unknown_user(store):
    srv = OrderService(InMemoryOrderRepository(store))
    with pytest.raises(NotFoundError):
        srv.create_order(99, 1, 1)


def test_unavailable_item(store):
    srv = OrderService(InMemoryOrderRepository(store))
    with pytest.raises(ValueError, match="недоступно"):
        srv.create_order(1, 2, 1)


def test_cancel_own_order(store):
    store.orders[1] = Order(1, 1, 1, 1, "processing")
    OrderService(InMemoryOrderRepository(store)).cancel_order(1, store.users[1])
    assert store.orders[1].status == "cancelled"


def test_cancel_foreign_order_idor(store):
    store.orders[1] = Order(1, 1, 1, 1, "processing")
    with pytest.raises(ForbiddenError):
        OrderService(InMemoryOrderRepository(store)).cancel_order(1, store.users[2])


def test_admin_can_cancel_foreign(store):
    store.orders[1] = Order(1, 1, 1, 1, "processing")
    OrderService(InMemoryOrderRepository(store)).cancel_order(1, store.users[4])
    assert store.orders[1].status == "cancelled"


def test_register_hashes_password(store):
    srv = UserService(InMemoryUserRepository(store))
    u = srv.register_user("new@sirius.ru", "secret123", "1234567890")
    assert u.password_hash and u.password_hash != "secret123"
    assert u.role == "student"
    with pytest.raises(ConflictError):
        srv.register_user("new@sirius.ru", "other")


def test_authenticate(store):
    srv = UserService(InMemoryUserRepository(store))
    srv.register_user("u@sirius.ru", "secret123")
    assert srv.authenticate("u@sirius.ru", "secret123").email == "u@sirius.ru"
    with pytest.raises(ValueError):
        srv.authenticate("u@sirius.ru", "wrong")


def test_topup(store):
    assert UserService(InMemoryUserRepository(store)).top_up_balance(1, 50) == 150.0


def test_topup_blocked(store):
    with pytest.raises(ForbiddenError):
        UserService(InMemoryUserRepository(store)).top_up_balance(3, 10)


def test_topup_limit(store):
    with pytest.raises(ValueError, match="50000"):
        UserService(InMemoryUserRepository(store)).top_up_balance(1, 50001)


def test_menu_duplicate(store):
    srv = MenuService(InMemoryMenuRepository(store))
    assert srv.create_menu_item("Суп", 25.0) == 3
    with pytest.raises(ValueError, match="уже существует"):
        srv.create_menu_item("Суп", 30.0)


def test_menu_update(store):
    MenuService(InMemoryMenuRepository(store)).update_menu_item(1, name=None, price=35.0, is_available=False)
    assert store.menu_items[1].price == 35.0
    assert store.menu_items[1].is_available is False


def test_assign_courier(store):
    store.orders[1] = Order(1, 1, 1, 1, "paid")
    srv = DeliveryService(InMemoryDeliveryRepository(store))
    assert srv.assign_courier(1, 2) == 1


def test_complete_own_delivery(store):
    store.orders[1] = Order(1, 1, 1, 1, "paid")
    store.deliveries[1] = Delivery(1, 1, 2, "in_progress")
    srv = DeliveryService(InMemoryDeliveryRepository(store))
    srv.complete_delivery(1, store.users[2])
    assert store.deliveries[1].status == "completed"
    assert store.orders[1].status == "delivered"


def test_complete_foreign_delivery_idor(store):
    store.orders[1] = Order(1, 1, 1, 1, "paid")
    store.deliveries[1] = Delivery(1, 1, 2, "in_progress")
    other = User(5, "o@sirius.ru", None, 0.0, False, "courier")
    store.users[5] = other
    with pytest.raises(ForbiddenError):
        DeliveryService(InMemoryDeliveryRepository(store)).complete_delivery(1, other)
