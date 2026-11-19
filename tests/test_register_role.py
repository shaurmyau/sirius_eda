"""Проверка регистрации с указанием роли."""
import os

os.environ["REPO_BACKEND"] = "memory"
os.environ["RATE_LIMIT_ENABLED"] = "False"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.entities import User  # noqa: E402
from app.main import app  # noqa: E402
from app.memory_store import memory_store  # noqa: E402
from app.permissions import permissions_for_role  # noqa: E402


@pytest.fixture
def client():
    memory_store.clear()
    return TestClient(app)


def _login(client, email, password="secret123"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _make_admin(client):
    """Готовим админа напрямую в in-memory store и логинимся."""
    memory_store.users[1] = User(
        id=1, email="admin@sirius.ru", phone=None, balance=0.0, is_blocked=False,
        role="admin", password_hash=hash_password("secret123"),
        permissions=frozenset(permissions_for_role("admin")),
    )
    return _login(client, "admin@sirius.ru")["access_token"]


def test_default_role_is_student(client):
    r = client.post("/users/register",
                    json={"email": "a@sirius.ru", "password": "secret123"})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "student"
    assert memory_store.users[body["user_id"]].role == "student"


def test_anonymous_can_register_cook_open_mode(client):
    """В учебном режиме роль принимается анонимно (см. README)."""
    r = client.post("/users/register",
                    json={"email": "c@sirius.ru", "password": "secret123",
                          "role": "cook"})
    assert r.status_code == 200
    assert r.json()["role"] == "cook"


def test_anonymous_can_register_admin_open_mode(client):
    """В учебном режиме роль admin тоже принимается (небезопасно, но так настроено)."""
    r = client.post("/users/register",
                    json={"email": "h@sirius.ru", "password": "secret123",
                          "role": "admin"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_student_token_can_register_cook_open_mode(client):
    client.post("/users/register",
                json={"email": "s@sirius.ru", "password": "secret123"})
    t = _login(client, "s@sirius.ru")
    r = client.post("/users/register",
                    json={"email": "c2@sirius.ru", "password": "secret123",
                          "role": "cook"},
                    headers={"Authorization": f"Bearer {t['access_token']}"})
    assert r.status_code == 200
    assert r.json()["role"] == "cook"


def test_admin_can_register_cook(client):
    admin_token = _make_admin(client)
    r = client.post("/users/register",
                    json={"email": "cook2@sirius.ru", "password": "secret123",
                          "role": "cook"},
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "cook"
    assert memory_store.users[body["user_id"]].role == "cook"
    # Повар имеет доступ к menu:write
    assert memory_store.users[body["user_id"]].has_permission("menu:write")


def test_admin_can_register_admin(client):
    admin_token = _make_admin(client)
    r = client.post("/users/register",
                    json={"email": "admin2@sirius.ru", "password": "secret123",
                          "role": "admin"},
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_unknown_role_rejected(client):
    admin_token = _make_admin(client)
    r = client.post("/users/register",
                    json={"email": "x@sirius.ru", "password": "secret123",
                          "role": "superhacker"},
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 400
    assert "Неизвестная роль" in r.json()["detail"]


def test_all_roles_accepted_by_admin(client):
    admin_token = _make_admin(client)
    h = {"Authorization": f"Bearer {admin_token}"}
    for role in ("student", "cook", "courier", "admin"):
        r = client.post("/users/register",
                        json={"email": f"{role}_x@sirius.ru",
                              "password": "secret123", "role": role},
                        headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["role"] == role
