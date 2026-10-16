"""Трансляция доменных исключений в HTTP."""
from fastapi import HTTPException

from app.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError


def to_http_error(error: ValueError) -> HTTPException:
    if isinstance(error, NotFoundError):
        status = 404
    elif isinstance(error, ForbiddenError):
        status = 403
    elif isinstance(error, UnauthorizedError):
        status = 401
    elif isinstance(error, ConflictError):
        status = 409
    else:
        status = 400
    return HTTPException(status_code=status, detail=str(error))
