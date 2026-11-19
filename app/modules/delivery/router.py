"""Транспортный слой delivery. RBAC: delivery:assign, delivery:read:self и т.д."""
from fastapi import APIRouter, Depends

from app.container import get_delivery_service
from app.core.dependencies import require_permission
from app.entities import User
from app.http_errors import to_http_error
from app.modules.delivery.service import DeliveryService
from app.permissions import Perm
from app.schemas import DeliveryAssign

router = APIRouter()


@router.post("/assign")
def assign_courier(payload: DeliveryAssign,
                   service: DeliveryService = Depends(get_delivery_service),
                   _u: User = Depends(require_permission(Perm.DELIVERY_ASSIGN))):
    try:
        did = service.assign_courier(payload.order_id, payload.courier_id)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "delivery_id": did}


@router.get("/my")
def my_deliveries(current_user: User = Depends(require_permission(Perm.DELIVERY_READ_SELF)),
                  service: DeliveryService = Depends(get_delivery_service)):
    try:
        return {"status": "success", "deliveries": service.list_my_deliveries(current_user)}
    except ValueError as e:
        raise to_http_error(e)


@router.get("/{delivery_id}")
def get_delivery(delivery_id: int,
                 current_user: User = Depends(require_permission(Perm.DELIVERY_READ_SELF)),
                 service: DeliveryService = Depends(get_delivery_service)):
    try:
        return {"status": "success",
                "delivery": service.get_delivery(delivery_id, current_user)}
    except ValueError as e:
        raise to_http_error(e)


@router.patch("/{delivery_id}/complete")
def complete_delivery(delivery_id: int,
                      current_user: User = Depends(require_permission(
                          Perm.DELIVERY_COMPLETE_SELF, Perm.DELIVERY_COMPLETE_ANY)),
                      service: DeliveryService = Depends(get_delivery_service)):
    try:
        service.complete_delivery(delivery_id, current_user)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success"}
