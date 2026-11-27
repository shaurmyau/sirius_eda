"""Pydantic-схемы."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    phone: str | None = None
    role: str | None = None


class UserResponse(BaseModel):
    id: int
    email: str
    balance: float

    class Config:
        from_attributes = True


class MenuItemCreate(BaseModel):
    name: str
    price: float
    category: Literal["food", "drink", "other"]


class MenuItemUpdate(BaseModel):
    name: str | None = None
    price: float | None = None
    is_available: bool | None = None
    category: Literal["food", "drink", "other"] | None = None


class OrderCreate(BaseModel):
    item_id: int
    quantity: int
    promo_code: str | None = Field(default=None, min_length=3, max_length=50)


class OrderPay(BaseModel):
    points_to_spend: Decimal = Field(default=Decimal('0.00'), ge=0)


class PromoCodeCreate(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    discount_type: Literal['percent', 'fixed']
    discount_value: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    valid_from: datetime
    valid_until: datetime
    max_uses: int | None = Field(default=None, ge=1)
    min_order_amount: Decimal = Field(default=Decimal('0.00'), ge=0, max_digits=12, decimal_places=2)
    is_active: bool = True


class DeliveryAssign(BaseModel):
    order_id: int
    courier_id: int


class LoginSchema(BaseModel):
    email: EmailStr
    password: str


class RefreshSchema(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
