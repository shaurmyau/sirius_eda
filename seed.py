"""Наполнение меню тестовыми блюдами (практическая работа № 8).

Идемпотентно: блюда с уже существующим названием не дублируются.
Запуск из корня проекта:  python seed.py
"""
from app.database import SessionLocal
from app.models import MenuItem
from app.modules.menu.repository import SqlMenuRepository

DISHES: list[tuple[str, float, str]] = [
    ("Сырники", 150, "food"),
    ("Борщ", 190, "food"),
    ("Паста карбонара", 320, "food"),
    ("Пицца Маргарита", 380, "food"),
    ("Оливье", 140, "food"),
    ("Куриный суп", 170, "food"),
    ("Американо", 110, "drink"),
    ("Капучино", 150, "drink"),
    ("Морс клюквенный", 90, "drink"),
    ("Круассан", 120, "other"),
]


def main() -> None:
    db = SessionLocal()
    try:
        existing = {name for (name,) in db.query(MenuItem.name).all()}
        added = 0
        for name, price, category in DISHES:
            if name in existing:
                continue
            db.add(MenuItem(name=name, price=price, is_available=True, category=category))
            added += 1
        db.commit()
        # Сбрасываем кеш Redis, чтобы /menu/items сразу увидел новые блюда.
        SqlMenuRepository(db).invalidate_cache()
        print(f"[seed] добавлено блюд: {added}, всего в справочнике: {len(existing) + added}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
