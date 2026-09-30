"""
Инфраструктурный слой модуля menu (Круг 3).
Абстрактный интерфейс и две реализации: SQL и in-memory.
"""
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.entities import MenuItem
from app.mappers import to_menu_item
from app.memory_store import MemoryStore
from app.models import MenuItem as MenuItemModel


class MenuRepository(ABC):
    """Интерфейс доступа к данным меню."""

    @abstractmethod
    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None: ...

    @abstractmethod
    def get_menu_item_by_name(self, name: str) -> MenuItem | None: ...

    @abstractmethod
    def save_menu_item(self, name: str, price: float) -> MenuItem:
        """Создаёт доступное блюдо."""

    @abstractmethod
    def update_menu_item(self, item: MenuItem) -> None:
        """Сохраняет изменённые поля блюда."""


class SqlMenuRepository(MenuRepository):
    """Реализация на PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None:
        row = self.db.query(MenuItemModel).filter(MenuItemModel.id == item_id).first()
        return to_menu_item(row)

    def get_menu_item_by_name(self, name: str) -> MenuItem | None:
        row = self.db.query(MenuItemModel).filter(MenuItemModel.name == name).first()
        return to_menu_item(row)

    def save_menu_item(self, name: str, price: float) -> MenuItem:
        row = MenuItemModel(name=name, price=price, is_available=True)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return to_menu_item(row)

    def update_menu_item(self, item: MenuItem) -> None:
        row = self.db.query(MenuItemModel).filter(MenuItemModel.id == item.id).first()
        row.name = item.name
        row.price = item.price
        row.is_available = item.is_available
        self.db.add(row)
        self.db.commit()


class InMemoryMenuRepository(MenuRepository):
    """Реализация в памяти (для тестов и запуска без СУБД)."""

    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None:
        return self.store.menu_items.get(item_id)

    def get_menu_item_by_name(self, name: str) -> MenuItem | None:
        for item in self.store.menu_items.values():
            if item.name == name:
                return item
        return None

    def save_menu_item(self, name: str, price: float) -> MenuItem:
        item = MenuItem(
            id=self.store.next_id(self.store.menu_items),
            name=name,
            price=price,
            is_available=True,
        )
        self.store.menu_items[item.id] = item
        return item

    def update_menu_item(self, item: MenuItem) -> None:
        self.store.menu_items[item.id] = item
