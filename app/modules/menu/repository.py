"""
Инфраструктурный слой модуля menu (Круги 3 + кеширование Lab 4).

Cache-Aside на Redis:
  • get_all()               -> ключ menu:all,               TTL 300s
  • list_by_category(cat)   -> ключ menu:category:{cat},    TTL 600s
  • get_all_json()          -> сырая строка из Redis (для быстрого отбоя)
  • get_category_json(cat)  -> сырая строка из Redis
  • invalidate_cache()      -> удаляет всё menu:*
  • warm_cache()            -> прогрев при старте приложения

Защита от cache stampede: Redis-lock + double-check + polling.
"""
import json
import logging
import time
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import record_menu_cache_operation
from app.core.redis import redis_client
from app.entities import MenuItem
from app.mappers import to_menu_item
from app.memory_store import MemoryStore
from app.models import MenuItem as MenuItemModel

log = logging.getLogger(__name__)

CACHE_KEY_ALL = "menu:all"
CACHE_KEY_CATEGORY = "menu:category:{category}"
LOCK_KEY_ALL = "lock:menu:all"
LOCK_KEY_CATEGORY = "lock:menu:category:{category}"
CACHE_CATEGORIES = ("food", "drink", "other")


def _serialize(item: MenuItem) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "price": item.price,
        "is_available": item.is_available,
        "category": item.category,
    }


def _deserialize(data: dict) -> MenuItem:
    return MenuItem(
        id=data["id"],
        name=data["name"],
        price=data["price"],
        is_available=data["is_available"],
        category=data.get("category", "food"),
    )


# ═══════════════════════════════════════════════════════════════════
#  ABC
# ═══════════════════════════════════════════════════════════════════
class MenuRepository(ABC):
    @abstractmethod
    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None: ...
    @abstractmethod
    def get_menu_item_by_name(self, name: str) -> MenuItem | None: ...
    @abstractmethod
    def get_all(self) -> list[MenuItem]: ...
    @abstractmethod
    def list_by_category(self, category: str) -> list[MenuItem]: ...
    @abstractmethod
    def save_menu_item(self, name: str, price: float, category: str = "food") -> MenuItem: ...
    @abstractmethod
    def update_menu_item(self, item: MenuItem) -> None: ...
    @abstractmethod
    def get_all_json(self) -> str | None: ...
    @abstractmethod
    def get_category_json(self, category: str) -> str | None: ...
    @abstractmethod
    def invalidate_cache(self) -> None: ...
    @abstractmethod
    def warm_cache(self) -> None: ...


# ═══════════════════════════════════════════════════════════════════
#  SQL + Redis (Cache-Aside)
# ═══════════════════════════════════════════════════════════════════
class SqlMenuRepository(MenuRepository):
    def __init__(self, db: Session):
        self.db = db

    # ---------- загрузчики из БД ----------
    def _fetch_all_from_db(self) -> list[MenuItem]:
        rows = self.db.query(MenuItemModel).order_by(MenuItemModel.id).all()
        return [to_menu_item(r) for r in rows]

    def _fetch_category_from_db(self, category: str) -> list[MenuItem]:
        rows = (
            self.db.query(MenuItemModel)
            .filter(MenuItemModel.category == category)
            .order_by(MenuItemModel.id)
            .all()
        )
        return [to_menu_item(r) for r in rows]

    # ---------- кеш ----------
    def _read_cache(self, key: str) -> list[MenuItem] | None:
        started_at = time.perf_counter()
        try:
            raw = redis_client.get(key)
            if raw is None:
                record_menu_cache_operation("read", "miss", started_at)
                return None
            data = json.loads(raw)
            if isinstance(data, dict) and "items" in data:
                result = [_deserialize(x) for x in data["items"]]
            else:
                result = [_deserialize(x) for x in data]
            record_menu_cache_operation("read", "hit", started_at)
            return result
        except Exception as exc:
            record_menu_cache_operation("read", "error", started_at)
            log.warning("cache read error [%s]: %s", key, exc)
            return None

    def _write_cache(self, key: str, items: list[MenuItem], ttl: int,
                     envelope: dict | None = None) -> None:
        started_at = time.perf_counter()
        try:
            if envelope is None:
                envelope = {"status": "success"}
            else:
                envelope = dict(envelope)
            envelope["items"] = [_serialize(i) for i in items]
            redis_client.setex(key, ttl, json.dumps(envelope))
            record_menu_cache_operation("write", "success", started_at)
        except Exception as exc:
            record_menu_cache_operation("write", "error", started_at)
            log.warning("cache write error [%s]: %s", key, exc)

    # ---------- Cache-Aside + anti-stampede ----------
    def _get_cached_or_load(self, cache_key: str, lock_key: str, loader, ttl: int,
                            envelope: dict | None = None) -> list[MenuItem]:
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        lock = None
        lock_started_at = time.perf_counter()
        try:
            lock = redis_client.lock(
                lock_key,
                timeout=settings.CACHE_STAMPEDE_LOCK_TIMEOUT,
                blocking_timeout=settings.CACHE_STAMPEDE_WAIT_TIMEOUT,
            )
            acquired = bool(lock.acquire(
                blocking=True,
                blocking_timeout=settings.CACHE_STAMPEDE_WAIT_TIMEOUT,
            ))
            record_menu_cache_operation(
                "lock", "acquired" if acquired else "timeout", lock_started_at
            )
        except Exception as exc:
            record_menu_cache_operation("lock", "error", lock_started_at)
            log.warning("cache lock failed [%s]: %s", cache_key, exc)
            return loader()

        if not acquired:
            wait_started_at = time.perf_counter()
            deadline = time.monotonic() + settings.CACHE_STAMPEDE_WAIT_TIMEOUT
            while time.monotonic() < deadline:
                time.sleep(settings.CACHE_STAMPEDE_RETRY_INTERVAL)
                cached = self._read_cache(cache_key)
                if cached is not None:
                    record_menu_cache_operation("lock_wait", "hit", wait_started_at)
                    return cached
            record_menu_cache_operation("lock_wait", "miss", wait_started_at)
            return loader()

        try:
            cached = self._read_cache(cache_key)   # double-check
            if cached is not None:
                return cached
            items = loader()
            self._write_cache(cache_key, items, ttl, envelope=envelope)
            return items
        finally:
            try:
                lock.release()
            except Exception:
                pass

    # ---------- public API ----------
    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None:
        row = self.db.query(MenuItemModel).filter(MenuItemModel.id == item_id).first()
        return to_menu_item(row)

    def get_menu_item_by_name(self, name: str) -> MenuItem | None:
        row = self.db.query(MenuItemModel).filter(MenuItemModel.name == name).first()
        return to_menu_item(row)

    def get_all(self) -> list[MenuItem]:
        return self._get_cached_or_load(
            CACHE_KEY_ALL, LOCK_KEY_ALL,
            self._fetch_all_from_db,
            settings.CACHE_MENU_ALL_TTL,
        )

    def list_by_category(self, category: str) -> list[MenuItem]:
        return self._get_cached_or_load(
            CACHE_KEY_CATEGORY.format(category=category),
            LOCK_KEY_CATEGORY.format(category=category),
            lambda: self._fetch_category_from_db(category),
            settings.CACHE_MENU_CATEGORY_TTL,
            envelope={"status": "success", "category": category},
        )

    def _read_cache_json(self, key: str) -> str | None:
        """Read a pre-serialized cache entry and instrument the fast HTTP path."""
        started_at = time.perf_counter()
        try:
            raw = redis_client.get(key)
            record_menu_cache_operation(
                "read", "hit" if raw is not None else "miss", started_at
            )
            return raw
        except Exception as exc:
            record_menu_cache_operation("read", "error", started_at)
            log.warning("cache read error [%s]: %s", key, exc)
            return None

    def get_all_json(self) -> str | None:
        return self._read_cache_json(CACHE_KEY_ALL)

    def get_category_json(self, category: str) -> str | None:
        key = CACHE_KEY_CATEGORY.format(category=category)
        return self._read_cache_json(key)

    def save_menu_item(self, name: str, price: float, category: str = "food") -> MenuItem:
        row = MenuItemModel(name=name, price=price, is_available=True, category=category)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return to_menu_item(row)

    def update_menu_item(self, item: MenuItem) -> None:
        row = self.db.query(MenuItemModel).filter(MenuItemModel.id == item.id).first()
        if row is None:
            return
        row.name = item.name
        row.price = item.price
        row.is_available = item.is_available
        row.category = item.category
        self.db.add(row)
        self.db.commit()

    def invalidate_cache(self) -> None:
        try:
            keys = [CACHE_KEY_ALL] + [
                CACHE_KEY_CATEGORY.format(category=c) for c in CACHE_CATEGORIES
            ]
            for k in keys:
                redis_client.delete(k)
        except Exception as exc:
            log.warning("cache invalidation error: %s", exc)

    def warm_cache(self) -> None:
        try:
            items = self._fetch_all_from_db()
            self._write_cache(CACHE_KEY_ALL, items, settings.CACHE_MENU_ALL_TTL)
            for cat in CACHE_CATEGORIES:
                cat_items = [i for i in items if i.category == cat]
                self._write_cache(
                    CACHE_KEY_CATEGORY.format(category=cat),
                    cat_items,
                    settings.CACHE_MENU_CATEGORY_TTL,
                    envelope={"status": "success", "category": cat},
                )
        except Exception as exc:
            log.warning("cache warm-up error: %s", exc)


# ═══════════════════════════════════════════════════════════════════
#  In-memory (для тестов)
# ═══════════════════════════════════════════════════════════════════
class InMemoryMenuRepository(MenuRepository):
    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None:
        return self.store.menu_items.get(item_id)

    def get_menu_item_by_name(self, name: str) -> MenuItem | None:
        for item in self.store.menu_items.values():
            if item.name == name:
                return item
        return None

    def get_all(self) -> list[MenuItem]:
        return list(self.store.menu_items.values())

    def list_by_category(self, category: str) -> list[MenuItem]:
        return [i for i in self.store.menu_items.values() if i.category == category]

    def save_menu_item(self, name: str, price: float, category: str = "food") -> MenuItem:
        item = MenuItem(
            id=self.store.next_id(self.store.menu_items),
            name=name, price=price, is_available=True, category=category,
        )
        self.store.menu_items[item.id] = item
        return item

    def update_menu_item(self, item: MenuItem) -> None:
        self.store.menu_items[item.id] = item

    def get_all_json(self) -> str | None:
        return None

    def get_category_json(self, category: str) -> str | None:
        return None

    def invalidate_cache(self) -> None:
        pass

    def warm_cache(self) -> None:
        pass
