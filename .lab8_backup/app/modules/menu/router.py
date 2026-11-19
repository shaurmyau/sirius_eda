"""Транспортный слой menu. RBAC: menu:write, menu:read."""
import traceback
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.container import get_menu_service
from app.core.dependencies import require_permission
from app.entities import User
from app.http_errors import to_http_error
from app.modules.menu.service import MenuService
from app.permissions import Perm
from app.schemas import MenuItemCreate, MenuItemUpdate

router = APIRouter()


@router.get("/items")
def list_menu(service: MenuService = Depends(get_menu_service)):
    """Всё меню. Cache-Aside: на hit — байты из Redis."""
    try:
        cached = service.get_menu_json()
        if cached is not None:
            return Response(content=cached, media_type="application/json")
        return {"status": "success", "items": service.get_menu()}
    except Exception as exc:
        print("=" * 60)
        print("[/menu/items] EXCEPTION:", repr(exc))
        traceback.print_exc()
        print("=" * 60)
        raise


@router.get("/categories/{category}")
def list_by_category(
    category: Literal["food", "drink", "other"],
    service: MenuService = Depends(get_menu_service),
):
    try:
        cached = service.get_category_json(category)
        if cached is not None:
            return Response(content=cached, media_type="application/json")
        return {
            "status": "success",
            "category": category,
            "items": service.get_menu_by_category(category),
        }
    except Exception as exc:
        print("=" * 60)
        print(f"[/menu/categories/{category}] EXCEPTION:", repr(exc))
        traceback.print_exc()
        print("=" * 60)
        raise


@router.post("/items")
def create_menu_item(
    payload: MenuItemCreate,
    service: MenuService = Depends(get_menu_service),
    _u: User = Depends(require_permission(Perm.MENU_WRITE)),
):
    if payload.price <= 0:
        raise HTTPException(400, "Цена должна быть положительной")
    if len(payload.name) < 2:
        raise HTTPException(400, "Название блюда слишком короткое")
    try:
        item_id = service.create_menu_item(payload.name, payload.price, payload.category)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "item_id": item_id}


@router.patch("/items/{item_id}")
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    service: MenuService = Depends(get_menu_service),
    _u: User = Depends(require_permission(Perm.MENU_WRITE)),
):
    if payload.price is not None and payload.price <= 0:
        raise HTTPException(400, "Цена должна быть положительной")
    try:
        upd = service.update_menu_item(
            item_id,
            name=payload.name,
            price=payload.price,
            is_available=payload.is_available,
            category=payload.category,
        )
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "item_id": upd}
