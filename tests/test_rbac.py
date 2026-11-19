"""Тесты ролевой модели: права ролей, RBAC-dependency, IDOR-разделение self/any."""
import pytest

from app.entities import User
from app.permissions import ROLE_PERMISSIONS, Perm


def test_role_matrix_has_core_permissions():
    """Проверяем, что ключевые права закреплены за ролями."""
    assert Perm.MENU_WRITE in ROLE_PERMISSIONS["cook"]
    assert Perm.MENU_WRITE not in ROLE_PERMISSIONS["student"]
    assert Perm.ORDERS_CREATE in ROLE_PERMISSIONS["student"]
    assert Perm.ORDERS_KITCHEN in ROLE_PERMISSIONS["cook"]
    assert Perm.ORDERS_KITCHEN not in ROLE_PERMISSIONS["student"]
    # У admin в матрице wildcard "*", проверяем именно это.
    assert ROLE_PERMISSIONS["admin"] == {"*"}
    # А конкретное право admin получает через has_permission (см. test_admin_has_wildcard)
    assert Perm.DELIVERY_ASSIGN not in ROLE_PERMISSIONS["courier"]


def test_has_permission_from_matrix_fallback():
    """User без явных permissions берёт их из матрицы роли."""
    cook = User(1, "c@sirius.ru", None, 0.0, False, role="cook")
    assert cook.has_permission(Perm.MENU_WRITE) is True
    assert cook.has_permission(Perm.ORDERS_CREATE) is False


def test_admin_has_wildcard():
    admin = User(1, "a@sirius.ru", None, 0.0, False, role="admin")
    for code in (Perm.ORDERS_CANCEL_ANY, Perm.USERS_BLOCK, Perm.DELIVERY_ASSIGN):
        assert admin.has_permission(code) is True


def test_explicit_permissions_override_role():
    """Если permissions заданы явно — используются они, не матрица."""
    student_with_extra = User(
        1, "s@sirius.ru", None, 0.0, False, role="student",
        permissions=frozenset({Perm.MENU_WRITE}),
    )
    assert student_with_extra.has_permission(Perm.MENU_WRITE) is True
    # ORDERS_CREATE у student есть в матрице, но раз permissions заданы явно — нет
    assert student_with_extra.has_permission(Perm.ORDERS_CREATE) is False


def test_wildcard_in_explicit_permissions():
    u = User(1, "x@sirius.ru", None, 0.0, False, role="student",
             permissions=frozenset({"*"}))
    assert u.has_permission("что-угодно:любое") is True


# --------- API-проверки: роли по-прежнему работают через permission ---------
import os
os.environ["REPO_BACKEND"] = "memory"
os.environ["RATE_LIMIT_ENABLED"] = "False"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.memory_store import memory_store  # noqa: E402


@pytest.fixture
def client():
    memory_store.clear()
    return TestClient(app)


def _register_and_login(client, email, password="secret123"):
    client.post("/users/register", json={"email": email, "password": password})
    r = client.post("/auth/login", json={"email": email, "password": password})
    return r.json()


def test_me_exposes_permissions(client):
    t = _register_and_login(client, "p@sirius.ru")
    r = client.get("/users/me", headers={"Authorization": f"Bearer {t['access_token']}"})
    body = r.json()
    assert body["role"] == "student"
    assert Perm.ORDERS_CREATE in body["permissions"]
    assert Perm.MENU_WRITE not in body["permissions"]


def test_student_cannot_use_menu_write(client):
    t = _register_and_login(client, "s3@sirius.ru")
    r = client.post("/menu/items", json={"name": "Борщ", "price": 30, "category": "food"},
                    headers={"Authorization": f"Bearer {t['access_token']}"})
    assert r.status_code == 403


def test_cook_can_create_menu_item(client):
    """Регистрируем cook напрямую в store, логинимся, создаём блюдо."""
    from app.core.security import hash_password
    memory_store.users[100] = User(
        100, "cook@sirius.ru", None, 0.0, False, role="cook",
        password_hash=hash_password("secret123"),
    )
    r = client.post("/auth/login", json={"email": "cook@sirius.ru", "password": "secret123"})
    token = r.json()["access_token"]
    r = client.post("/menu/items", json={"name": "Борщ", "price": 30, "category": "food"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
