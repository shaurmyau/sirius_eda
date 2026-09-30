"""
Сущности предметной области (Круг 1 модели Мартина).
Обычные dataclass: никаких зависимостей от ORM и веб-фреймворка.
"""
from dataclasses import dataclass


@dataclass
class User:
    id: int
    email: str
    phone: str | None
    balance: float
    is_blocked: bool


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
