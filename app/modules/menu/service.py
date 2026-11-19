"""
Слой бизнес-логики модуля menu (Круги 1 и 2).
Не зависит от fastapi, sqlalchemy и redis (см. tests/test_architecture.py).
"""
from app.exceptions import NotFoundError
from app.modules.menu.repository import MenuRepository

VALID_CATEGORIES = ("food", "drink", "other")


class MenuService:
    def __init__(self, repository: MenuRepository):
        self.repository = repository

    def create_menu_item(self, name: str, price: float, category: str = "food") -> int:
        if self.repository.get_menu_item_by_name(name):
            raise ValueError("Блюдо с таким названием уже существует")
        saved = self.repository.save_menu_item(name, price, category)
        self.repository.invalidate_cache()
        return saved.id

    def update_menu_item(
        self,
        item_id: int,
        name: str | None,
        price: float | None,
        is_available: bool | None,
        category: str | None = None,
    ) -> int:
        item = self.repository.get_menu_item_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")

        if name is not None:
            item.name = name
        if price is not None:
            item.price = price
        if is_available is not None:
            item.is_available = is_available
        if category is not None:
            if category not in VALID_CATEGORIES:
                raise ValueError(f"Неизвестная категория: {category}")
            item.category = category

        self.repository.update_menu_item(item)
        self.repository.invalidate_cache()
        return item.id

    def get_menu_json(self) -> str | None:
        return self.repository.get_all_json()

    def get_category_json(self, category: str) -> str | None:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Неизвестная категория: {category}")
        return self.repository.get_category_json(category)

    def get_menu(self) -> list[dict]:
        return [self._to_dict(i) for i in self.repository.get_all()]

    def get_menu_by_category(self, category: str) -> list[dict]:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Неизвестная категория: {category}")
        return [self._to_dict(i) for i in self.repository.list_by_category(category)]

    def get_menu_item(self, item_id: int) -> dict:
        item = self.repository.get_menu_item_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")
        return self._to_dict(item)

    @staticmethod
    def _to_dict(item) -> dict:
        return {
            "id": item.id,
            "name": item.name,
            "price": item.price,
            "is_available": item.is_available,
            "category": item.category,
        }
