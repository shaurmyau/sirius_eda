"""Каталог прав и матрица «роль → права» (доменный уровень, без ORM/fastapi)."""


class Perm:
    USERS_READ = "users:read"
    USERS_TOPUP_SELF = "users:topup:self"
    USERS_TOPUP_ANY = "users:topup:any"
    USERS_BLOCK = "users:block"
    USERS_ASSIGN_ROLE = "users:assign_role"

    MENU_READ = "menu:read"
    MENU_WRITE = "menu:write"

    ORDERS_CREATE = "orders:create"
    ORDERS_READ_SELF = "orders:read:self"
    ORDERS_READ_ANY = "orders:read:any"
    ORDERS_CANCEL_SELF = "orders:cancel:self"
    ORDERS_CANCEL_ANY = "orders:cancel:any"
    ORDERS_KITCHEN = "orders:kitchen"

    DELIVERY_ASSIGN = "delivery:assign"
    DELIVERY_READ_SELF = "delivery:read:self"
    DELIVERY_READ_ANY = "delivery:read:any"
    DELIVERY_COMPLETE_SELF = "delivery:complete:self"
    DELIVERY_COMPLETE_ANY = "delivery:complete:any"


ALL_PERMISSIONS: dict[str, str] = {
    Perm.USERS_READ: "Просмотр пользователей",
    Perm.USERS_TOPUP_SELF: "Пополнение своего баланса",
    Perm.USERS_TOPUP_ANY: "Пополнение чужого баланса",
    Perm.USERS_BLOCK: "Блокировка пользователей",
    Perm.USERS_ASSIGN_ROLE: "Назначение ролей при регистрации",
    Perm.MENU_READ: "Просмотр меню",
    Perm.MENU_WRITE: "Изменение меню",
    Perm.ORDERS_CREATE: "Создание заказов",
    Perm.ORDERS_READ_SELF: "Просмотр своих заказов",
    Perm.ORDERS_READ_ANY: "Просмотр любых заказов",
    Perm.ORDERS_CANCEL_SELF: "Отмена своих заказов",
    Perm.ORDERS_CANCEL_ANY: "Отмена чужих заказов",
    Perm.ORDERS_KITCHEN: "Доступ к кухонному экрану",
    Perm.DELIVERY_ASSIGN: "Назначение курьера",
    Perm.DELIVERY_READ_SELF: "Просмотр своих доставок",
    Perm.DELIVERY_READ_ANY: "Просмотр любых доставок",
    Perm.DELIVERY_COMPLETE_SELF: "Завершение своей доставки",
    Perm.DELIVERY_COMPLETE_ANY: "Завершение любой доставки",
}


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "student": {
        Perm.USERS_READ,
        Perm.USERS_TOPUP_SELF,
        Perm.MENU_READ,
        Perm.ORDERS_CREATE,
        Perm.ORDERS_READ_SELF,
        Perm.ORDERS_CANCEL_SELF,
        Perm.DELIVERY_READ_SELF,
    },
    "cook": {
        Perm.USERS_READ,
        Perm.USERS_TOPUP_SELF,
        Perm.MENU_READ,
        Perm.MENU_WRITE,
        Perm.ORDERS_READ_ANY,
        Perm.ORDERS_KITCHEN,
    },
    "courier": {
        Perm.USERS_READ,
        Perm.USERS_TOPUP_SELF,
        Perm.MENU_READ,
        Perm.ORDERS_READ_ANY,
        Perm.DELIVERY_READ_SELF,
        Perm.DELIVERY_COMPLETE_SELF,
    },
    "admin": {"*"},
}


def permissions_for_role(role: str) -> set[str]:
    """Возвращает набор permission-кодов для роли."""
    return set(ROLE_PERMISSIONS.get(role, set()))
