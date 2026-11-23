"""HTTP -> Service -> Repository -> real PostgreSQL integration test."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import models
from app.container import get_order_service
from app.core.dependencies import get_current_user
from app.entities import User as DomainUser
from app.main import app
from app.modules.orders.repository import SqlOrderRepository
from app.modules.orders.service import OrderService
from app.permissions import Perm


pytestmark = pytest.mark.integration


def test_create_order_persists_and_debits_balance_in_postgres(
    postgres_session, monkeypatch
):
    """A real migrated PostgreSQL database is used; no shared dev DB is touched."""
    import app.modules.orders.service as service_module

    monkeypatch.setattr(service_module.generate_order_pdf, "delay", lambda *_a, **_k: None)
    monkeypatch.setattr(service_module.send_order_email, "delay", lambda *_a, **_k: None)

    db = postgres_session
    user_row = models.User(
        email="lab10-postgres-integration@sirius.test",
        balance=1000.0,
        is_blocked=False,
    )
    item_row = models.MenuItem(
        name="Lab 10 integration dish",
        price=150.0,
        is_available=True,
        category="food",
    )
    db.add_all([user_row, item_row])
    db.flush()

    principal = DomainUser(
        id=user_row.id,
        email=user_row.email,
        phone=None,
        balance=1000.0,
        is_blocked=False,
        role="student",
        permissions=frozenset({Perm.ORDERS_CREATE}),
    )
    service = OrderService(SqlOrderRepository(db), publisher=None)

    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_order_service] = lambda: service
    try:
        # Deliberately do not enter TestClient as a context manager: this test
        # exercises the request stack, not production startup side effects.
        response = TestClient(app).post(
            "/orders/create",
            json={"item_id": item_row.id, "quantity": 2},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_order_service, None)

    assert response.status_code == 200, response.text
    order_id = response.json()["order_id"]

    persisted = db.get(models.Order, order_id)
    refreshed_user = db.get(models.User, user_row.id)
    assert persisted is not None
    assert persisted.user_id == user_row.id
    assert persisted.item_id == item_row.id
    assert persisted.quantity == 2
    assert persisted.status == "processing"
    assert refreshed_user.balance == 700.0
