"""
Транспортный слой модуля delivery (Круг 4).
"""
from fastapi import APIRouter, Depends

from app.container import get_delivery_service
from app.http_errors import to_http_error
from app.modules.delivery.service import DeliveryService
from app.schemas import DeliveryAssign

router = APIRouter()


@router.post("/assign")
def assign_courier(
    payload: DeliveryAssign,
    service: DeliveryService = Depends(get_delivery_service),
):
    try:
        delivery_id = service.assign_courier(payload.order_id, payload.courier_id)
    except ValueError as e:
        raise to_http_error(e)

    return {"status": "success", "delivery_id": delivery_id}


@router.patch("/{delivery_id}/complete")
def complete_delivery(
    delivery_id: int,
    service: DeliveryService = Depends(get_delivery_service),
):
    try:
        service.complete_delivery(delivery_id)
    except ValueError as e:
        raise to_http_error(e)

    return {"status": "success"}
