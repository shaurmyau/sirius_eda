"""Точка входа."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401
from app.container import use_memory_backend
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.delivery.router import router as delivery_router
from app.modules.menu.router import router as menu_router
from app.modules.orders.router import router as orders_router
from app.modules.users.router import router as users_router

# Практическая работа № 9: observability включается без изменения бизнес-логики.
from app.core.logging import setup_logging
from app.core.correlation import correlation_id_middleware
from app.core.metrics import metrics_middleware
from app.core.sentry import setup_sentry
from app.core.tracing import setup_tracing
from prometheus_fastapi_instrumentator import Instrumentator

setup_logging()
setup_sentry()

log = logging.getLogger("app.startup")


def _seed() -> None:
    try:
        from app.database import seed_permissions
        seed_permissions()
        print("[startup] seed_permissions: ok")
    except Exception as exc:
        print(f"[startup][WARN] seed_permissions: {exc}")


def _warm() -> None:
    try:
        from app.core.redis import check_redis_connection
        if not check_redis_connection():
            print("[startup] Redis недоступен — прогрев кеша пропущен")
            return
        from app.database import SessionLocal
        from app.modules.menu.repository import SqlMenuRepository
        db = SessionLocal()
        try:
            SqlMenuRepository(db).warm_cache()
            print("[startup] warm_cache: ok")
        finally:
            db.close()
    except Exception as exc:
        print(f"[startup][WARN] warm_cache: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not use_memory_backend():
        _seed()
        _warm()
    else:
        print("[startup] REPO_BACKEND=memory — seed/warm пропущены")
    print("[startup] Application startup complete")
    yield
    print("[shutdown] Bye")


app = FastAPI(
    title="Sirius.Food API",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    debug=settings.DEBUG,          # ← traceback в теле 500-ответа
    lifespan=lifespan,
)

# X-Correlation-ID проходит через все HTTP-обработчики.
app.middleware("http")(correlation_id_middleware)
app.middleware("http")(metrics_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
    expose_headers=["X-Correlation-ID"],
)

# RED-метрики HTTP: запросы, статусы и длительность.
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
setup_tracing(app)

# Временный endpoint для проверки Sentry. По умолчанию выключен.
if settings.DEBUG and __import__("os").getenv("OBSERVABILITY_TEST_ENDPOINT", "false").lower() == "true":
    @app.get("/observability/test-error", include_in_schema=False)
    async def observability_test_error():
        raise RuntimeError("Sirius.Eda observability test exception")

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(users_router, prefix="/users", tags=["users"])
app.include_router(menu_router, prefix="/menu", tags=["menu"])
app.include_router(orders_router, prefix="/orders", tags=["orders"])
app.include_router(delivery_router, prefix="/delivery", tags=["delivery"])
