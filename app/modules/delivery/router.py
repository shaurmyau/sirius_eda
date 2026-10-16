"""Транспортный слой delivery."""
from fastapi import APIRouter, Depends

from app.container import get_delivery_service
from app.core.dependencies import get_current_user, require_role
from app.entities import User
from app.http_errors import to_http_error
from app.modules.delivery.service import DeliveryService
from app.schemas import DeliveryAssign

router = APIRouter()


@router.post("/assign")
def assign_courier(payload: DeliveryAssign,
                   service: DeliveryService = Depends(get_delivery_service),
                   _u: User = Depends(require_role("admin"))):
    try:
        did = service.assign_courier(payload.order_id, payload.courier_id)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success", "delivery_id": did}


@router.patch("/{delivery_id}/complete")
def complete_delivery(delivery_id: int,
                      current_user: User = Depends(get_current_user),
                      service: DeliveryService = Depends(get_delivery_service)):
    try:
        service.complete_delivery(delivery_id, current_user)
    except ValueError as e:
        raise to_http_error(e)
    return {"status": "success"}
