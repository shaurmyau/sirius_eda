"""Транспортный слой orders."""
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_order_service
from app.core.dependencies import get_current_user, require_role
from app.entities import User
from app.http_errors import to_http_error
from app.modules.orders.service import OrderService
from app.schemas import OrderCreate

router = APIRouter()


@router.post("/create")
def create_order(payload: OrderCreate,
                 current_user: User = Depends(get_current_user),
                 service: OrderService = Depends(get_order_service)):
    if payload.quantity <= 0:
        raise HTTPException(400, "Количество должно быть больше нуля")
    try:
        # user_id берём из JWT, не из payload.
        oid = service.create_order(current_user.id, payload.item_id, payload.quantity)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "order_id": oid}


@router.post("/{order_id}/cancel")
def cancel_order(order_id: int,
                 current_user: User = Depends(get_current_user),
                 service: OrderService = Depends(get_order_service)):
    try:
        service.cancel_order(order_id, current_user)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success"}


@router.get("/kitchen/orders")
def kitchen_orders(_u: User = Depends(require_role("cook"))):
    return {"status": "success", "orders": []}
