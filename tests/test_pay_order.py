"""OrderService.pay_order и POST /orders/{id}/pay (in-memory, без брокера)."""
import pytest
from fastapi.testclient import TestClient

from app.entities import MenuItem, Order, User
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.main import app
from app.memory_store import MemoryStore, memory_store
from app.modules.orders.repository import InMemoryOrderRepository
from app.modules.orders.service import OrderService


@pytest.fixture
def store():
    s = MemoryStore()
    s.users[1] = User(1, "student@sirius.ru", None, 100.0, False, "student")
    s.users[2] = User(2, "other@sirius.ru", None, 100.0, False, "student")
    s.users[3] = User(3, "admin@sirius.ru", None, 0.0, False, "admin")
    s.menu_items[1] = MenuItem(1, "Борщ", 30.0, True)
    s.orders[1] = Order(1, 1, 1, 2, "processing")
    return s


def _service(store, publisher):
    return OrderService(InMemoryOrderRepository(store), publisher=publisher)


def test_pay_publishes_order_paid(store):
    sent = []
    _service(store, lambda rk, p: sent.append((rk, p))).pay_order(1, store.users[1])
    assert store.orders[1].status == "paid"
    assert len(sent) == 1
    routing_key, payload = sent[0]
    assert routing_key == "order.paid"
    assert payload["order_id"] == 1
    assert payload["customer_id"] == 1
    assert payload["amount"] == 60.0  # backward-compatible field for delivery/Saga
    assert payload["total"] == 60.0
    assert payload["currency"] == "RUB"
    assert payload["event_id"]


def test_pay_event_ids_are_unique(store):
    sent = []
    srv = _service(store, lambda rk, p: sent.append(p))
    srv.pay_order(1, store.users[1])
    store.orders[1].status = "processing"
    srv.pay_order(1, store.users[1])
    assert sent[0]["event_id"] != sent[1]["event_id"]


def test_pay_foreign_order_forbidden(store):
    with pytest.raises(ForbiddenError):
        _service(store, None).pay_order(1, store.users[2])
    assert store.orders[1].status == "processing"


def test_admin_can_pay_foreign(store):
    _service(store, None).pay_order(1, store.users[3])
    assert store.orders[1].status == "paid"


def test_pay_twice_conflict(store):
    srv = _service(store, None)
    srv.pay_order(1, store.users[1])
    with pytest.raises(ConflictError):
        srv.pay_order(1, store.users[1])


def test_pay_cancelled_order_rejected(store):
    store.orders[1].status = "cancelled"
    with pytest.raises(ValueError, match="нельзя оплатить"):
        _service(store, None).pay_order(1, store.users[1])


def test_pay_unknown_order(store):
    with pytest.raises(NotFoundError):
        _service(store, None).pay_order(99, store.users[1])


def test_publisher_failure_does_not_break_payment(store):
    def broken(rk, payload):
        raise ConnectionError("RabbitMQ недоступен")

    _service(store, broken).pay_order(1, store.users[1])
    assert store.orders[1].status == "paid"


# ----------------------------- HTTP-уровень ---------------------------------
@pytest.fixture
def client():
    memory_store.clear()
    return TestClient(app)


def _login(client, email, password="secret123"):
    assert client.post("/users/register", json={"email": email, "password": password}).status_code == 200
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_pay_endpoint(client):
    ha = _login(client, "pa@a.com")
    hb = _login(client, "pb@b.com")
    memory_store.menu_items[1] = MenuItem(1, "Борщ", 30.0, True)
    memory_store.orders[1] = Order(1, 1, 1, 1, "processing")

    assert client.post("/orders/1/pay", headers=hb).status_code == 403   # чужой заказ
    assert client.post("/orders/99/pay", headers=ha).status_code == 404
    assert client.post("/orders/1/pay").status_code == 401               # без токена

    r = client.post("/orders/1/pay", headers=ha)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "success", "order_status": "paid"}
    assert memory_store.orders[1].status == "paid"
    assert client.post("/orders/1/pay", headers=ha).status_code == 409   # повторная оплата
