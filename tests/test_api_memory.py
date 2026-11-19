"""API-тесты + безопасность (in-memory, без PostgreSQL)."""
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


def _login(client, email, password="secret123"):
    r = client.post("/users/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def test_full_flow(client):
    t = _login(client, "s@sirius.ru")
    h = {"Authorization": f"Bearer {t['access_token']}"}

    assert client.post("/users/me/topup", params={"amount": 100}, headers=h).json()["new_balance"] == 100.0
    memory_store.menu_items[1] = MenuItem(1, "Борщ", 30.0, True)
    r = client.post("/orders/create", json={"item_id": 1, "quantity": 2}, headers=h)
    assert r.json() == {"status": "success", "order_id": 1}
    assert client.post("/users/me/topup", params={"amount": 10}, headers=h).json()["new_balance"] == 50.0
    assert client.post("/orders/create", json={"item_id": 1, "quantity": 100}, headers=h).status_code == 400
    assert client.post("/orders/create", json={"item_id": 1, "quantity": 0}, headers=h).status_code == 400


def test_no_token_401(client):
    assert client.post("/orders/create", json={"item_id": 1, "quantity": 1}).status_code == 401


def test_wrong_role_403(client):
    t = _login(client, "s2@sirius.ru")
    h = {"Authorization": f"Bearer {t['access_token']}"}
    r = client.post("/menu/items", json={"name": "Борщ", "price": 30}, headers=h)
    assert r.status_code == 403


def test_idor_foreign_order_403(client):
    ta = _login(client, "a@a.com")
    tb = _login(client, "b@b.com")
    ha = {"Authorization": f"Bearer {ta['access_token']}"}
    hb = {"Authorization": f"Bearer {tb['access_token']}"}
    client.post("/users/me/topup", params={"amount": 100}, headers=ha)
    memory_store.menu_items[1] = MenuItem(1, "Борщ", 30.0, True)
    oid = client.post("/orders/create", json={"item_id": 1, "quantity": 1}, headers=ha).json()["order_id"]
    assert client.post(f"/orders/{oid}/cancel", headers=hb).status_code == 403


def test_refresh_rotation(client):
    t = _login(client, "r@r.com")
    old = t["refresh_token"]
    r = client.post("/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 200
    new = r.json()["refresh_token"]
    assert new != old
    # Повторное использование — 401 + сброс всей сессии.
    assert client.post("/auth/refresh", json={"refresh_token": old}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": new}).status_code == 401

# =============================================================================
# Rate limiting (429) — изолированный тест без реального Redis.
# =============================================================================
class _FakeRedis:
    """Минимальный in-memory аналог Redis для проверки rate limit."""
    def __init__(self):
        self.data: dict[str, int] = {}

    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    def expire(self, key, ttl):
        return True


def test_rate_limit_429(client, monkeypatch):
    """6-й запрос к /auth/login в окне 60с → 429.

    Подменяем модуль app.core.rate_limit._redis на фейк и включаем флаг,
    чтобы не зависеть от реального Redis в CI.
    """
    from app.core import rate_limit as rl

    monkeypatch.setattr(rl, "_redis", _FakeRedis())
    monkeypatch.setattr(rl.settings, "RATE_LIMIT_ENABLED", True)

    # регистрируем, чтобы аккаунт существовал (email любой — важно, что запросы идут)
    client.post("/users/register", json={"email": "rl@test.ru", "password": "secret123"})

    codes = []
    for _ in range(6):
        r = client.post("/auth/login", json={"email": "rl@test.ru", "password": "wrong"})
        codes.append(r.status_code)

    assert codes[0] == 401, codes            # первые 5 — неверный пароль
    assert codes[-1] == 429, codes           # 6-й — заблокирован
    assert codes.count(429) >= 1, codes
