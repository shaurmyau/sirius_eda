"""Focused unit tests used by mutmut (no database, broker or FastAPI)."""
import pytest

from app.entities import MenuItem, Order, User
from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.memory_store import MemoryStore
from app.modules.orders.repository import InMemoryOrderRepository
from app.modules.orders.service import OrderService


@pytest.fixture
def store():
    state = MemoryStore()
    state.users[1] = User(1, "owner@sirius.test", None, 500.0, False, "student")
    state.users[2] = User(2, "stranger@sirius.test", None, 500.0, False, "student")
    state.users[3] = User(3, "admin@sirius.test", None, 0.0, False, "admin")
    state.menu_items[10] = MenuItem(10, "Soup", 100.0, True)
    state.menu_items[11] = MenuItem(11, "Unavailable", 50.0, False)
    state.orders[20] = Order(20, 1, 10, 2, "processing")
    return state


def service(store, publisher=None):
    return OrderService(InMemoryOrderRepository(store), publisher=publisher)


def test_create_order_debits_exact_total_and_persists_processing(store, monkeypatch):
    import app.modules.orders.service as module

    monkeypatch.setattr(module.generate_order_pdf, "delay", lambda *_a, **_k: None)
    monkeypatch.setattr(module.send_order_email, "delay", lambda *_a, **_k: None)

    order_id = service(store).create_order(1, 10, 3)
    assert order_id == 21
    assert store.users[1].balance == 200.0
    assert store.orders[order_id] == Order(order_id, 1, 10, 3, "processing")


def test_create_order_rejects_unknown_user_and_unknown_item(store):
    with pytest.raises(NotFoundError, match="Пользователь"):
        service(store).create_order(999, 10, 1)
    with pytest.raises(NotFoundError, match="Блюдо"):
        service(store).create_order(1, 999, 1)


def test_create_order_rejects_unavailable_item_and_insufficient_balance(store):
    with pytest.raises(ValueError, match="недоступно"):
        service(store).create_order(1, 11, 1)
    with pytest.raises(ValueError, match="Недостаточно"):
        service(store).create_order(1, 10, 6)
    assert store.users[1].balance == 500.0


def test_cancel_order_checks_owner_and_allowed_status(store):
    with pytest.raises(ForbiddenError) as error:
        service(store).cancel_order(20, store.users[2])
    assert str(error.value) == "Нельзя отменить чужой заказ"

    service(store).cancel_order(20, store.users[1])
    assert store.orders[20].status == "cancelled"

    with pytest.raises(ValueError) as error:
        service(store).cancel_order(20, store.users[1])
    assert str(error.value) == "Заказ нельзя отменить в текущем статусе"


def test_admin_can_cancel_foreign_order_but_unknown_order_is_404(store):
    service(store).cancel_order(20, store.users[3])
    assert store.orders[20].status == "cancelled"
    with pytest.raises(NotFoundError) as error:
        service(store).cancel_order(999, store.users[3])
    assert str(error.value) == "Заказ не найден"


def test_pay_order_publishes_rub_total_and_preserves_legacy_amount(store):
    emitted = []
    service(store, lambda key, payload: emitted.append((key, payload))).pay_order(
        20, store.users[1]
    )
    assert store.orders[20].status == "paid"
    assert len(emitted) == 1
    key, payload = emitted[0]
    assert key == "order.paid"
    assert payload["order_id"] == 20
    assert payload["customer_id"] == 1
    assert payload["total"] == 200.0
    assert payload["currency"] == "RUB"
    assert payload["amount"] == 200.0
    assert payload["event_id"]
    assert payload["occurred_at"]


def test_pay_order_enforces_owner_and_state(store):
    with pytest.raises(ForbiddenError) as error:
        service(store).pay_order(20, store.users[2])
    assert str(error.value) == "Нельзя оплатить чужой заказ"

    service(store).pay_order(20, store.users[1])

    with pytest.raises(ConflictError) as error:
        service(store).pay_order(20, store.users[1])
    assert str(error.value) == "Заказ уже оплачен"

    with pytest.raises(NotFoundError) as error:
        service(store).pay_order(999, store.users[1])
    assert str(error.value) == "Заказ не найден"


def test_pay_order_rejects_cancelled_order_and_handles_missing_publisher(store):
    store.orders[20].status = "cancelled"
    with pytest.raises(ValueError) as error:
        service(store).pay_order(20, store.users[1])
    assert str(error.value) == "Заказ нельзя оплатить в текущем статусе"
    store.orders[20].status = "processing"
    service(store, publisher=None).pay_order(20, store.users[1])
    assert store.orders[20].status == "paid"



def test_create_order_accepts_balance_equal_to_total(store, monkeypatch):
    import app.modules.orders.service as module

    monkeypatch.setattr(module.generate_order_pdf, "delay", lambda *_a, **_k: None)
    monkeypatch.setattr(module.send_order_email, "delay", lambda *_a, **_k: None)
    store.users[1].balance = 200.0

    order_id = service(store).create_order(1, 10, 2)

    assert store.orders[order_id].status == "processing"
    assert store.users[1].balance == 0.0


def test_create_order_raises_exact_domain_errors(store):
    with pytest.raises(NotFoundError) as error:
        service(store).create_order(999, 10, 1)
    assert str(error.value) == "Пользователь не найден"

    with pytest.raises(NotFoundError) as error:
        service(store).create_order(1, 999, 1)
    assert str(error.value) == "Блюдо не найдено"

    with pytest.raises(ValueError) as error:
        service(store).create_order(1, 11, 1)
    assert str(error.value) == "Блюдо недоступно"

    with pytest.raises(ValueError) as error:
        service(store).create_order(1, 10, 6)
    assert str(error.value) == "Недостаточно средств на балансе студента"


def test_paid_order_is_cancellable(store):
    store.orders[20].status = "paid"
    service(store).cancel_order(20, store.users[1])
    assert store.orders[20].status == "cancelled"


def test_pay_order_admin_can_pay_foreign_order(store):
    service(store).pay_order(20, store.users[3])
    assert store.orders[20].status == "paid"


def test_pay_order_uses_zero_amount_when_menu_item_is_missing(store):
    emitted = []
    store.menu_items.pop(10)
    service(store, lambda key, payload: emitted.append((key, payload))).pay_order(
        20, store.users[1]
    )
    assert store.orders[20].status == "paid"
    assert len(emitted) == 1
    assert emitted[0][1]["amount"] == 0.0
    assert emitted[0][1]["total"] == 0.0


def test_publish_failure_is_logged_with_routing_key_and_order_id(store, caplog):
    import logging

    def broken_publisher(_routing_key, _payload):
        raise RuntimeError("broker unavailable")

    with caplog.at_level(logging.ERROR, logger="orders.events"):
        service(store, broken_publisher)._publish("order.paid", {"order_id": 20})

    assert any(
        record.getMessage() == "Не удалось опубликовать order.paid (order_id=20)"
        for record in caplog.records
    )
    assert any(
        record.exc_info and record.exc_info[0] is RuntimeError
        for record in caplog.records
    )


def test_list_my_orders_returns_only_own_orders_with_public_fields(store):
    store.orders[21] = Order(21, 2, 10, 1, "paid")
    result = service(store).list_my_orders(store.users[1])
    assert result == [
        {"id": 20, "item_id": 10, "quantity": 2, "status": "processing"}
    ]
