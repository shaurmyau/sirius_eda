"""Транспортный слой auth."""
from fastapi import APIRouter, Depends

from app.container import get_auth_service
from app.core.rate_limit import rate_limit
from app.http_errors import to_http_error
from app.modules.auth.service import AuthService
from app.schemas import LoginSchema, RefreshSchema, TokenResponse

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginSchema,
          service: AuthService = Depends(get_auth_service),
          _: None = Depends(rate_limit(5, 60))):
    try:
        return service.login(payload.email, payload.password)
    except ValueError as e:
        raise to_http_error(e)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshSchema,
            service: AuthService = Depends(get_auth_service)):
    try:
        return service.refresh(payload.refresh_token)
    except ValueError as e:
        raise to_http_error(e)
