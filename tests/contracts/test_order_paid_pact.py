"""Pact V3 asynchronous-message contract: kitchen <-> monolith.

This test runs both sides of the contract:
* the Pact example is delivered to the real kitchen handler;
* the provider verifier checks the event emitted by OrderService.pay_order.
"""
from __future__ import annotations

import json

import pytest
from pact import Pact, Verifier, match

from app import models
from app.entities import MenuItem as DomainMenuItem
from app.entities import Order as DomainOrder
from app.entities import User as DomainUser
from app.memory_store import MemoryStore
from app.modules.orders.repository import InMemoryOrderRepository
from app.modules.orders.service import OrderService
from app.workers.handlers import handle_order_paid_kitchen

pytestmark = pytest.mark.contract

DESCRIPTION = "Kitchen receives an OrderPaid event after an order is paid"


def test_order_paid_message_contract_is_compatible_with_both_sides(
    session_factory, tmp_path
):
    # Stable IDs let the Pact consumer example be handled against an isolated
    # SQLite database while the provider event is produced by OrderService.
    db = session_factory()
    db.add_all(
        [
            models.User(id=41, email="pact-student@sirius.test", balance=0.0),
            models.MenuItem(
                id=12, name="Pact dish", price=150.0,
                is_available=True, category="food",
            ),
            models.Order(
                id=55, user_id=41, item_id=12, quantity=2, status="paid",
            ),
        ]
    )
    db.commit()

    # Exercise the actual producer path rather than a hand-written payload.
    store = MemoryStore()
    principal = DomainUser(
        id=41, email="pact-student@sirius.test", phone=None,
        balance=0.0, is_blocked=False, role="student",
    )
    store.users[41] = principal
    store.menu_items[12] = DomainMenuItem(
        id=12, name="Pact dish", price=150.0, is_available=True,
    )
    store.orders[55] = DomainOrder(
        id=55, user_id=41, item_id=12, quantity=2, status="processing",
    )
    published: list[tuple[str, dict]] = []
    OrderService(
        InMemoryOrderRepository(store),
        publisher=lambda routing_key, payload: published.append((routing_key, payload)),
    ).pay_order(55, principal)

    routing_key, actual_event = published[0]
    assert routing_key == "order.paid"

    pact = Pact("kitchen", "sirius-monolith").with_specification("V3")
    (
        pact.upon_receiving(DESCRIPTION, "Async")
        .given("order 55 has been paid")
        .with_body(
            {
                "event_id": match.str("event-example-55"),
                "order_id": match.int(55),
                "total": match.float(300.0),
                "currency": match.str("RUB"),
            },
            content_type="application/json",
        )
    )

    # Consumer verification: the kitchen handler must accept the contract
    # message and create exactly one kitchen-order record.
    def kitchen_handler(body, _metadata):
        payload = json.loads(body)
        handle_order_paid_kitchen(db, payload)

    pact.verify(kitchen_handler, "Async")
    assert (
        db.query(models.KitchenOrder).filter_by(order_id=55).count() == 1
    )

    # Provider verification: Pact replays the same interaction against the
    # payload produced by the real OrderService. Extra backward-compatible
    # fields (amount, customer_id, occurred_at) are allowed by Pact matching.
    pact_dir = tmp_path / "pacts"
    pact.write_file(pact_dir, overwrite=True)
    verifier = (
        Verifier("sirius-monolith")
        .message_handler(
            {
                DESCRIPTION: {
                    "contents": json.dumps(actual_event),
                    "metadata": {"contentType": "application/json"},
                    "content_type": "application/json",
                }
            }
        )
        .add_source(str(pact_dir))
    )
    verifier.verify()
    db.close()
