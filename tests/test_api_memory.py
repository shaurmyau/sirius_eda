"""
Проверка API целиком на in-memory репозиториях (без PostgreSQL).
Доказывает, что реализацию репозитория можно заменить,
не меняя ни service.py, ни router.py.
"""
import os

os.environ["REPO_BACKEND"] = "memory"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.memory_store import memory_store  # noqa: E402


@pytest.fixture
def client():
    memory_store.clear()
    return TestClient(app)


def test_full_flow(client):
    r = client.post("/users/register", json={"email": "student@sirius.ru", "phone": "1234567890"})
    assert r.status_code == 200
    assert r.json() == {"status": "success", "user_id": 1, "email": "student@sirius.ru"}

    r = client.post("/users/1/topup", params={"amount": 100})
    assert r.json() == {"status": "success", "new_balance": 100.0}

    r = client.post("/menu/items", json={"name": "Борщ", "price": 30})
    assert r.json() == {"status": "success", "item_id": 1}

    r = client.post("/orders/create", json={"user_id": 1, "item_id": 1, "quantity": 2})
    assert r.status_code == 200
    assert r.json() == {"status": "success", "order_id": 1}

    r = client.post("/users/1/topup", params={"amount": 10})
    assert r.json()["new_balance"] == 50.0  # 100 - 2*30 + 10

    # Коды ошибок сохранены как в исходном MVP
    r = client.post("/orders/create", json={"user_id": 1, "item_id": 1, "quantity": 0})
    assert r.status_code == 400
    r = client.post("/orders/create", json={"user_id": 99, "item_id": 1, "quantity": 1})
    assert r.status_code == 404
    r = client.post("/orders/create", json={"user_id": 1, "item_id": 1, "quantity": 100})
    assert r.status_code == 400

    # Доставка
    client.post("/users/register", json={"email": "courier@sirius.ru"})
    memory_store.orders[1].status = "paid"

    r = client.post("/delivery/assign", json={"order_id": 1, "courier_id": 2})
    assert r.json() == {"status": "success", "delivery_id": 1}

    r = client.patch("/delivery/1/complete")
    assert r.json() == {"status": "success"}
    assert memory_store.orders[1].status == "delivered"

    r = client.patch("/delivery/1/complete")
    assert r.status_code == 400
