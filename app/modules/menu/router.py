"""Транспортный слой menu. RBAC: cook/admin."""
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_menu_service
from app.core.dependencies import require_role
from app.entities import User
from app.http_errors import to_http_error
from app.modules.menu.service import MenuService
from app.schemas import MenuItemCreate, MenuItemUpdate

router = APIRouter()


@router.post("/items")
def create_menu_item(payload: MenuItemCreate,
                     service: MenuService = Depends(get_menu_service),
                     _u: User = Depends(require_role("cook"))):
    if payload.price <= 0:
        raise HTTPException(400, "Цена должна быть положительной")
    if len(payload.name) < 2:
        raise HTTPException(400, "Название блюда слишком короткое")
    try:
        item_id = service.create_menu_item(payload.name, payload.price)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "item_id": item_id}


@router.patch("/items/{item_id}")
def update_menu_item(item_id: int, payload: MenuItemUpdate,
                     service: MenuService = Depends(get_menu_service),
                     _u: User = Depends(require_role("cook"))):
    if payload.price is not None and payload.price <= 0:
        raise HTTPException(400, "Цена должна быть положительной")
    try:
        upd = service.update_menu_item(item_id, name=payload.name,
                                       price=payload.price,
                                       is_available=payload.is_available)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "item_id": upd}
