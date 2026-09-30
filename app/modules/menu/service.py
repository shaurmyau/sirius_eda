"""
Слой бизнес-логики модуля menu (Круги 1 и 2).
Не зависит от fastapi и sqlalchemy.
"""
from app.exceptions import NotFoundError
from app.modules.menu.repository import MenuRepository


class MenuService:
    """Бизнес-правила работы с меню."""

    def __init__(self, repository: MenuRepository):
        # Внедрение зависимости через конструктор (инверсия зависимостей).
        self.repository = repository

    def create_menu_item(self, name: str, price: float) -> int:
        """Создаёт блюдо и возвращает его id. ValueError, если название занято."""
        if self.repository.get_menu_item_by_name(name):
            raise ValueError("Блюдо с таким названием уже существует")
        return self.repository.save_menu_item(name, price).id

    def update_menu_item(
        self,
        item_id: int,
        name: str | None,
        price: float | None,
        is_available: bool | None,
    ) -> int:
        """Обновляет переданные поля блюда и возвращает его id."""
        item = self.repository.get_menu_item_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")

        if name is not None:
            item.name = name
        if price is not None:
            item.price = price
        if is_available is not None:
            item.is_available = is_available

        self.repository.update_menu_item(item)
        return item.id
