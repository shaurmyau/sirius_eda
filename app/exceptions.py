"""
Доменные исключения. Наследуются от ValueError, поэтому сервис
по-прежнему «возбуждает ValueError при нарушении бизнес-правил».
Обычный ValueError -> HTTP 400, NotFoundError -> 404, ForbiddenError -> 403.
"""


class NotFoundError(ValueError):
    """Запрошенный объект не найден."""


class ForbiddenError(ValueError):
    """Операция запрещена (например, пользователь заблокирован)."""
