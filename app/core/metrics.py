# Дополнительные метрики бизнес-эндпоинтов Sirius.Еда.
from __future__ import annotations

import time
from fastapi import Request
from prometheus_client import Counter, Histogram

ORDERS_CREATE_REQUESTS = Counter(
    "sirius_orders_create_requests_total",
    "Количество HTTP-попыток создания заказа.",
)
MENU_ITEMS_LATENCY = Histogram(
    "sirius_menu_items_request_duration_seconds",
    "Время ответа GET /menu/items в секундах.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.5, 5.0, 10.0),
)


async def metrics_middleware(request: Request, call_next):
    # Считает RED-метрики для двух контрольных маршрутов из задания.
    path = request.url.path
    measure_menu = request.method == "GET" and path == "/menu/items"
    if request.method == "POST" and path == "/orders/create":
        ORDERS_CREATE_REQUESTS.inc()

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        if measure_menu:
            MENU_ITEMS_LATENCY.observe(time.perf_counter() - started)
        raise

    if measure_menu:
        MENU_ITEMS_LATENCY.observe(time.perf_counter() - started)
    return response
