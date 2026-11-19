"""GET /menu/items/{id} — эндпоинт для SSR-карточки блюда (in-memory)."""
import os

os.environ["REPO_BACKEND"] = "memory"
os.environ["RATE_LIMIT_ENABLED"] = "False"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.entities import MenuItem  # noqa: E402
from app.main import app  # noqa: E402
from app.memory_store import memory_store  # noqa: E402


@pytest.fixture
def client():
    memory_store.clear()
    return TestClient(app)


def test_get_menu_item_ok(client):
    memory_store.menu_items[1] = MenuItem(1, "Сырники", 150.0, True, "food")
    r = client.get("/menu/items/1")
    assert r.status_code == 200
    assert r.json() == {
        "id": 1,
        "name": "Сырники",
        "price": 150.0,
        "is_available": True,
        "category": "food",
    }


def test_get_menu_item_not_found(client):
    r = client.get("/menu/items/999999")
    assert r.status_code == 404
