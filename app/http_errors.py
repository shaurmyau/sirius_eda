"""
Трансляция доменных исключений в HTTP-ответы (транспортный слой).
"""
from fastapi import HTTPException

from app.exceptions import ForbiddenError, NotFoundError


def to_http_error(error: ValueError) -> HTTPException:
    if isinstance(error, NotFoundError):
        status = 404
    elif isinstance(error, ForbiddenError):
        status = 403
    else:
        status = 400
    return HTTPException(status_code=status, detail=str(error))
