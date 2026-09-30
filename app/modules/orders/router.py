"""
Транспортный слой модуля orders (Круг 4).
"""
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_order_service
from app.http_errors import to_http_error
from app.modules.orders.service import OrderService
from app.schemas import OrderCreate

router = APIRouter()


@router.post("/create")
def create_order(payload: OrderCreate, service: OrderService = Depends(get_order_service)):
    # Техническая валидация уровня транспортного протокола.
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Количество должно быть больше нуля")

    # Делегирование сценария слою бизнес-логики.
    try:
        order_id = service.create_order(
            user_id=payload.user_id,
            item_id=payload.item_id,
            quantity=payload.quantity,
        )
    except ValueError as e:
        # Трансляция внутреннего исключения в HTTP-статус.
        raise to_http_error(e)

    return {"status": "success", "order_id": order_id}
