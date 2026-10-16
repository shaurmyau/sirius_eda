"""Сущности предметной области (dataclass, без ORM)."""
from dataclasses import dataclass


@dataclass
class User:
    id: int
    email: str
    phone: str | None
    balance: float
    is_blocked: bool
    role: str = "student"
    password_hash: str | None = None


@dataclass
class MenuItem:
    id: int
    name: str
    price: float
    is_available: bool


@dataclass
class Order:
    id: int
    user_id: int
    item_id: int
    quantity: int
    status: str


@dataclass
class Delivery:
    id: int
    order_id: int
    courier_id: int | None
    status: str
