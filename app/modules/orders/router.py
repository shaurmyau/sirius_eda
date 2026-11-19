"""Транспортный слой orders. RBAC: orders:create, orders:kitchen и т.д."""
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_order_service
from app.core.dependencies import get_current_user, require_permission
from app.entities import User
from app.http_errors import to_http_error
from app.modules.orders.service import OrderService
from app.permissions import Perm
from app.schemas import OrderCreate

router = APIRouter()


@router.post("/create")
def create_order(payload: OrderCreate,
                 current_user: User = Depends(require_permission(Perm.ORDERS_CREATE)),
                 service: OrderService = Depends(get_order_service)):
    if payload.quantity <= 0:
        raise HTTPException(400, "Количество должно быть больше нуля")
    try:
        oid = service.create_order(current_user.id, payload.item_id, payload.quantity)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "order_id": oid}


@router.get("/my")
def my_orders(current_user: User = Depends(require_permission(Perm.ORDERS_READ_SELF)),
              service: OrderService = Depends(get_order_service)):
    return {"status": "success", "orders": service.list_my_orders(current_user)}


@router.post("/{order_id}/cancel")
def cancel_order(order_id: int,
                 current_user: User = Depends(require_permission(
                     Perm.ORDERS_CANCEL_SELF, Perm.ORDERS_CANCEL_ANY)),
                 service: OrderService = Depends(get_order_service)):
    try:
        service.cancel_order(order_id, current_user)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success"}


@router.get("/kitchen/orders")
def kitchen_orders(_u: User = Depends(require_permission(Perm.ORDERS_KITCHEN))):
    return {"status": "success", "orders": []}


@router.post("/{order_id}/pay")
def pay_order(order_id: int,
              current_user: User = Depends(require_permission(Perm.ORDERS_CREATE)),
              service: OrderService = Depends(get_order_service)):
    """Оплата заказа. После оплаты публикуется событие order.paid в RabbitMQ."""
    try:
        service.pay_order(order_id, current_user)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "order_status": "paid"}
