"""Чистые бизнес-правила трека A: сроки и расчёт скидки."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def as_decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def validate_promo(promo, subtotal: Decimal, *, now: datetime | None = None) -> None:
    """Проверяет применимость промокода; вызывается под блокировкой строки."""
    now = utc_naive(now or datetime.now(timezone.utc))
    valid_from = utc_naive(promo.valid_from)
    valid_until = utc_naive(promo.valid_until)
    if not promo.is_active:
        raise ValueError("Промокод неактивен")
    if valid_from and now < valid_from:
        raise ValueError("Срок действия промокода ещё не начался")
    if valid_until and now > valid_until:
        raise ValueError("Срок действия промокода истёк")
    if promo.max_uses is not None and promo.current_uses >= promo.max_uses:
        raise ValueError("Промокод исчерпан")
    if subtotal < as_decimal(promo.min_order_amount):
        raise ValueError("Сумма заказа меньше минимальной для промокода")


def calculate_discount(promo, subtotal: Decimal) -> Decimal:
    """Возвращает скидку в рублях, округлённую до копеек и не выше суммы заказа."""
    value = as_decimal(promo.discount_value)
    if promo.discount_type == "percent":
        discount = (subtotal * value / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    elif promo.discount_type == "fixed":
        discount = value.quantize(CENT, rounding=ROUND_HALF_UP)
    else:
        raise ValueError("Неизвестный тип скидки")
    return min(max(discount, Decimal("0.00")), subtotal)
