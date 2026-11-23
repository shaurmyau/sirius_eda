"""Canonical event payloads shared by OrderService and contract tests.

The kitchen contract requires order_id, total and currency.  The legacy
amount field remains present because delivery and saga consumers already
consume it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def build_order_paid_event(
    *,
    order_id: int,
    customer_id: int,
    total: float,
    event_id: str | None = None,
    occurred_at: str | None = None,
    currency: str = "RUB",
) -> dict[str, Any]:
    """Build the stable OrderPaid message consumed by kitchen and delivery."""
    normalized_total = float(total)
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "order_id": int(order_id),
        "customer_id": int(customer_id),
        "total": normalized_total,
        "currency": currency,
        # Backward-compatible alias used by delivery and Saga handlers.
        "amount": normalized_total,
        "occurred_at": occurred_at or datetime.now(timezone.utc).isoformat(),
    }
