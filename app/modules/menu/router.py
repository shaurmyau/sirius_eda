"""
Транспортный слой модуля menu (Круг 4).
"""
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_menu_service
from app.http_errors import to_http_error
from app.modules.menu.service import MenuService
from app.schemas import MenuItemCreate, MenuItemUpdate

router = APIRouter()


@router.post("/items")
def create_menu_item(payload: MenuItemCreate, service: MenuService = Depends(get_menu_service)):
    # Техническая валидация цены и названия.
    if payload.price <= 0:
        raise HTTPException(status_code=400, detail="Цена должна быть положительной")
    if len(payload.name) < 2:
        raise HTTPException(status_code=400, detail="Название блюда слишком короткое")

    try:
        item_id = service.create_menu_item(payload.name, payload.price)
    except ValueError as e:
        raise to_http_error(e)

    return {"status": "success", "item_id": item_id}


@router.patch("/items/{item_id}")
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    service: MenuService = Depends(get_menu_service),
):
    # Техническая валидация нового значения цены.
    if payload.price is not None and payload.price <= 0:
        raise HTTPException(status_code=400, detail="Цена должна быть положительной")

    try:
        updated_id = service.update_menu_item(
            item_id,
            name=payload.name,
            price=payload.price,
            is_available=payload.is_available,
        )
    except ValueError as e:
        raise to_http_error(e)

    return {"status": "success", "item_id": updated_id}
