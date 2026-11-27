"""Точка входа."""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401
from app.container import use_memory_backend
from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.delivery.router import router as delivery_router
from app.modules.menu.router import router as menu_router
from app.modules.orders.router import router as orders_router
from app.modules.orders.websocket import router as order_websocket_router
from app.modules.promotions.router import router as promotions_router
from app.modules.loyalty.router import router as loyalty_router
from app.core.websocket_manager import order_ws_manager
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
    # У каждой реплики собственные WebSocket-соединения и общий Redis Pub/Sub.
    redis_listener = None
    if not use_memory_backend():
        redis_listener = asyncio.create_task(order_ws_manager.run_redis_listener())
    print("[startup] Application startup complete")
    try:
        yield
    finally:
        if redis_listener is not None:
            redis_listener.cancel()
            with suppress(asyncio.CancelledError):
                await redis_listener
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
app.include_router(order_websocket_router, tags=["order-tracking"])
app.include_router(promotions_router, prefix="/promos", tags=["promotions"])
app.include_router(loyalty_router, prefix="/loyalty", tags=["loyalty"])
app.include_router(delivery_router, prefix="/delivery", tags=["delivery"])
