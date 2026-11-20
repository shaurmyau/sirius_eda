#!/usr/bin/env bash
# Практическая работа № 9 — Observability для проекта Sirius.Eda.
# Запускать из корня репозитория: bash /path/to/apply_observability.sh
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

for required in app/main.py app/core/rabbitmq.py app/workers/base.py requirements.txt docker-compose.yml README.md; do
  if [[ ! -f "$required" ]]; then
    echo "ОШИБКА: не найден $required. Запустите скрипт из корня sirius_eda." >&2
    exit 1
  fi
done

BACKUP_DIR=".backups/observability_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
FILES_TO_BACKUP=(
  app/main.py
  app/core/rabbitmq.py
  app/workers/base.py
  app/workers/handlers.py
  requirements.txt
  docker-compose.yml
  README.md
  start.sh
  .gitignore
  app/core/correlation.py
  app/core/logging.py
  app/core/tracing.py
  app/core/sentry.py
  prometheus/prometheus.yml
  grafana/provisioning/datasources/prometheus.yml
  grafana/provisioning/dashboards/provider.yml
  grafana/dashboards/sirius-observability.json
  observability.env.example
)
for file in "${FILES_TO_BACKUP[@]}"; do
  if [[ -f "$file" ]]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$file")"
    cp -a "$file" "$BACKUP_DIR/$file"
  fi
done

echo "==> Резервные копии изменяемых файлов: $BACKUP_DIR"

python3 - <<'PY'
from __future__ import annotations

import json
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Не удалось обновить {label}: не найден ожидаемый фрагмент {old!r}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# requirements.txt — только добавляем отсутствующие зависимости.
# ---------------------------------------------------------------------------
requirements = read("requirements.txt")
new_requirements = [
    "structlog>=24.1.0",
    "prometheus-fastapi-instrumentator>=7.0.0",
    "sentry-sdk[fastapi]>=2.0.0",
    "opentelemetry-api>=1.25.0",
    "opentelemetry-sdk>=1.25.0",
    "opentelemetry-exporter-otlp-proto-grpc>=1.25.0",
    "opentelemetry-instrumentation-fastapi>=0.46b0",
]
existing_names = set()
for line in requirements.splitlines():
    stripped = line.strip()
    if stripped and not stripped.startswith("#"):
        existing_names.add(re.split(r"[<=>\[; ]", stripped, maxsplit=1)[0].lower().replace("_", "-"))
for dependency in new_requirements:
    name = re.split(r"[<=>\[; ]", dependency, maxsplit=1)[0].lower().replace("_", "-")
    if name not in existing_names:
        requirements = requirements.rstrip() + "\n" + dependency + "\n"
        existing_names.add(name)
write("requirements.txt", requirements)


# ---------------------------------------------------------------------------
# Observability modules.
# ---------------------------------------------------------------------------
write("app/core/logging.py", r'''"""Единая настройка структурированных JSON-логов в stdout."""
from __future__ import annotations

import logging
import sys

import structlog


def setup_logging() -> None:
    """Направляет stdlib logging и structlog в единый JSON-формат stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(ensure_ascii=False),
            foreign_pre_chain=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
''')

write("app/core/metrics.py", r'''# Дополнительные метрики бизнес-эндпоинтов Sirius.Еда.
from __future__ import annotations

import time
from fastapi import Request
from prometheus_client import Counter, Histogram

ORDERS_CREATE_REQUESTS = Counter(
    "sirius_orders_create_requests_total",
    "Количество HTTP-попыток создания заказа.",
)
MENU_ITEMS_LATENCY = Histogram(
    "sirius_menu_items_request_duration_seconds",
    "Время ответа GET /menu/items в секундах.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.5, 5.0, 10.0),
)


async def metrics_middleware(request: Request, call_next):
    # Считает RED-метрики для двух контрольных маршрутов из задания.
    path = request.url.path
    measure_menu = request.method == "GET" and path == "/menu/items"
    if request.method == "POST" and path == "/orders/create":
        ORDERS_CREATE_REQUESTS.inc()

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        if measure_menu:
            MENU_ITEMS_LATENCY.observe(time.perf_counter() - started)
        raise

    if measure_menu:
        MENU_ITEMS_LATENCY.observe(time.perf_counter() - started)
    return response
''')

write("app/core/correlation.py", r'''"""Сквозной correlation_id для HTTP-запросов и фоновых consumer'ов."""
from __future__ import annotations

import time
import uuid
from contextvars import ContextVar, Token

import structlog
from fastapi import Request

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
log = structlog.get_logger("http")


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> Token:
    return _correlation_id.set(value)


def reset_correlation_id(token: Token) -> None:
    _correlation_id.reset(token)


async def correlation_id_middleware(request: Request, call_next):
    """Принимает/создаёт ID, привязывает его к логам и возвращает клиенту."""
    supplied = request.headers.get("X-Correlation-ID", "").strip()
    correlation_id = supplied[:128] if supplied else str(uuid.uuid4())
    token = set_correlation_id(correlation_id)
    request.state.correlation_id = correlation_id

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

    try:
        try:
            from opentelemetry import trace
            span = trace.get_current_span()
            if span and span.is_recording():
                span.set_attribute("correlation_id", correlation_id)
        except Exception:
            pass

        try:
            import sentry_sdk
            sentry_sdk.set_tag("correlation_id", correlation_id)
        except Exception:
            pass

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "http_request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                correlation_id=correlation_id,
            )
            raise

        response.headers["X-Correlation-ID"] = correlation_id
        log.info(
            "http_request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            correlation_id=correlation_id,
        )
        return response
    finally:
        structlog.contextvars.clear_contextvars()
        reset_correlation_id(token)
''')

write("app/core/sentry.py", r'''"""Необязательная интеграция Sentry; активируется переменной SENTRY_DSN."""
from __future__ import annotations

import logging
import os

log = logging.getLogger("observability.sentry")
_initialized = False


def setup_sentry() -> bool:
    global _initialized
    if _initialized:
        return True

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        log.info("Sentry не включён: SENTRY_DSN не задан")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
            integrations=[StarletteIntegration(), FastApiIntegration()],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            send_default_pii=False,
        )
        _initialized = True
        log.info("Sentry инициализирован")
        return True
    except Exception:
        log.exception("Не удалось инициализировать Sentry")
        return False
''')

write("app/core/tracing.py", r'''"""OpenTelemetry: FastAPI + ручные spans для RabbitMQ publisher/consumer."""
from __future__ import annotations

import logging
import os

log = logging.getLogger("observability.tracing")
_initialized = False


def setup_tracing(app=None, service_name: str | None = None) -> bool:
    """Подключает OTLP exporter и, при передаче app, FastAPI instrumentation."""
    global _initialized
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    enabled = os.getenv("OTEL_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
    if not enabled:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        if not _initialized:
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
            service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "sirius-app")
            provider = TracerProvider(
                resource=Resource.create(
                    {
                        "service.name": service_name,
                        "service.namespace": "sirius-eda",
                        "deployment.environment.name": os.getenv("SENTRY_ENVIRONMENT", "development"),
                    }
                )
            )
            exporter = OTLPSpanExporter(
                endpoint=endpoint,
                insecure=not endpoint.startswith("https://"),
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            _initialized = True
            log.info("OpenTelemetry настроен", service_name=service_name, endpoint=endpoint)

        if app is not None and not getattr(app.state, "otel_instrumented", False):
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app, excluded_urls=r".*/metrics$")
            app.state.otel_instrumented = True
        return True
    except Exception:
        log.exception("OpenTelemetry не удалось включить; приложение продолжит работу")
        return False


def get_tracer(name: str = "sirius-eda"):
    from opentelemetry import trace
    return trace.get_tracer(name)
''')


# ---------------------------------------------------------------------------
# FastAPI entry point: add middleware, metrics, optional OTel/Sentry.
# ---------------------------------------------------------------------------
main = read("app/main.py")
if "from app.core.logging import setup_logging" not in main:
    anchor = "from app.modules.users.router import router as users_router\n"
    imports = (
        "\n"
        "# Практическая работа № 9: observability включается без изменения бизнес-логики.\n"
        "from app.core.logging import setup_logging\n"
        "from app.core.correlation import correlation_id_middleware\n"
        "from app.core.metrics import metrics_middleware\n"
        "from app.core.sentry import setup_sentry\n"
        "from app.core.tracing import setup_tracing\n"
        "from prometheus_fastapi_instrumentator import Instrumentator\n"
        "\n"
        "setup_logging()\n"
        "setup_sentry()\n"
    )
    main = replace_once(main, anchor, anchor + imports, "импорты observability в app/main.py")

if 'app.middleware("http")(correlation_id_middleware)' not in main:
    anchor = "    lifespan=lifespan,\n)\n"
    addition = (
        "    lifespan=lifespan,\n)\n\n"
        "# X-Correlation-ID проходит через все HTTP-обработчики.\n"
        'app.middleware("http")(correlation_id_middleware)\n'
        'app.middleware("http")(metrics_middleware)\n'
    )
    main = replace_once(main, anchor, addition, "correlation middleware в app/main.py")

main = main.replace(
    'allow_headers=["Authorization", "Content-Type"],',
    'allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],\n'
    '    expose_headers=["X-Correlation-ID"],',
)
if "Instrumentator().instrument(app).expose" not in main:
    anchor = '    expose_headers=["X-Correlation-ID"],\n)\n'
    if anchor not in main:
        anchor = '    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],\n)\n'
    addition = (
        anchor
        + "\n# RED-метрики HTTP: запросы, статусы и длительность.\n"
        'Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)\n'
        "setup_tracing(app)\n"
    )
    main = replace_once(main, anchor, addition, "Prometheus/OTel hooks в app/main.py")

if "OBSERVABILITY_TEST_ENDPOINT" not in main:
    anchor = 'setup_tracing(app)\n'
    test_route = (
        'setup_tracing(app)\n\n'
        '# Временный endpoint для проверки Sentry. По умолчанию выключен.\n'
        'if settings.DEBUG and __import__("os").getenv("OBSERVABILITY_TEST_ENDPOINT", "false").lower() == "true":\n'
        '    @app.get("/observability/test-error", include_in_schema=False)\n'
        '    async def observability_test_error():\n'
        '        raise RuntimeError("Sirius.Eda observability test exception")\n'
    )
    main = replace_once(main, anchor, test_route, "тестовый Sentry endpoint")

write("app/main.py", main)


# ---------------------------------------------------------------------------
# RabbitMQ publisher: copy correlation id and W3C trace context into headers.
# ---------------------------------------------------------------------------
rabbitmq = read("app/core/rabbitmq.py")
if "from app.core.correlation import get_correlation_id" not in rabbitmq:
    rabbitmq = replace_once(
        rabbitmq,
        "from app.core.config import settings\n",
        "from app.core.config import settings\n"
        "from app.core.correlation import get_correlation_id\n"
        "from app.core.tracing import get_tracer\n",
        "импорты RabbitMQ propagation",
    )

start = rabbitmq.find("def _build_message(")
end = rabbitmq.find("def publish_event_sync(")
if start < 0 or end < 0 or end <= start:
    raise SystemExit("Не удалось найти _build_message/publish_event в app/core/rabbitmq.py")
new_publisher = r'''def _build_message(payload: dict, headers: dict | None = None) -> aio_pika.Message:
    return aio_pika.Message(
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
        message_id=str(payload.get("event_id", "")) or None,
        headers=headers or {},
    )


async def publish_event(routing_key: str, payload: dict, *, exchange=None) -> None:
    """Публикует событие с correlation_id и W3C traceparent в AMQP headers."""
    tracer = get_tracer("sirius.rabbitmq")
    with tracer.start_as_current_span(f"rabbitmq.publish {routing_key}") as span:
        span.set_attribute("messaging.system", "rabbitmq")
        span.set_attribute("messaging.destination.name", routing_key)
        span.set_attribute("messaging.operation", "publish")
        if payload.get("order_id") is not None:
            span.set_attribute("order.id", str(payload["order_id"]))

        headers: dict = {}
        try:
            from opentelemetry.propagate import inject
            inject(headers)  # traceparent/baggage родительского span'а.
        except Exception:
            log.debug("OpenTelemetry context injection пропущен", exc_info=True)

        correlation_id = get_correlation_id()
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id

        message = _build_message(payload, headers)
        if exchange is not None:
            await exchange.publish(message, routing_key=routing_key)
        else:
            connection = await get_connection()
            async with connection:
                channel = await connection.channel()
                exchange, _ = await declare_topology(channel)
                await exchange.publish(message, routing_key=routing_key)

    log.info("published %s event_id=%s", routing_key, payload.get("event_id"))

'''
rabbitmq = rabbitmq[:start] + new_publisher + rabbitmq[end:]
write("app/core/rabbitmq.py", rabbitmq)


# ---------------------------------------------------------------------------
# RabbitMQ consumer base: extract context, span, JSON logs and same correlation.
# ---------------------------------------------------------------------------
base = read("app/workers/base.py")
if "from app.core.correlation import" not in base:
    base = replace_once(
        base,
        "from app.workers.handlers import OutEvent\n",
        "from app.workers.handlers import OutEvent\n"
        "from app.core.correlation import set_correlation_id, reset_correlation_id\n"
        "from app.core.logging import setup_logging\n"
        "from app.core.sentry import setup_sentry\n"
        "from app.core.tracing import setup_tracing, get_tracer\n"
        "from opentelemetry import propagate\n"
        "from opentelemetry.trace import SpanKind, Status, StatusCode\n"
        "import structlog\n",
        "импорты observability в app/workers/base.py",
    )

proc_start = base.find("def make_processor(")
proc_end = base.find("async def start_consumer(")
if proc_start < 0 or proc_end < 0 or proc_end <= proc_start:
    raise SystemExit("Не удалось найти make_processor в app/workers/base.py")
new_processor = r'''def make_processor(spec: ConsumerSpec, session_factory, exchange):
    async def on_message(message) -> None:
        headers = message.headers or {}
        correlation_id = str(headers.get("X-Correlation-ID") or "unknown")
        token = set_correlation_id(correlation_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            service=f"{spec.name}-consumer",
        )
        parent_context = propagate.extract(headers)
        tracer = get_tracer(f"sirius.worker.{spec.name}")

        try:
            with tracer.start_as_current_span(
                f"{spec.name}.consume",
                context=parent_context,
                kind=SpanKind.CONSUMER,
            ) as span:
                span.set_attribute("messaging.system", "rabbitmq")
                span.set_attribute("messaging.destination.name", spec.queue.name)
                span.set_attribute("messaging.operation", "process")
                if message.message_id:
                    span.set_attribute("messaging.message.id", str(message.message_id))

                try:
                    async with message.process(requeue=True, reject_on_redelivered=True):
                        payload = json.loads(message.body)
                        if not isinstance(payload, dict):
                            raise ValueError("payload должен быть JSON-объектом")
                        if payload.get("order_id") is not None:
                            span.set_attribute("order.id", str(payload["order_id"]))

                        log.info(
                            "message_received",
                            consumer=spec.name,
                            queue=spec.queue.name,
                            order_id=payload.get("order_id"),
                            event_id=payload.get("event_id"),
                            correlation_id=correlation_id,
                        )

                        db = session_factory()
                        try:
                            outgoing = spec.handler(db, payload)
                        except Exception:
                            db.rollback()
                            raise
                        finally:
                            db.close()

                        for routing_key, body in outgoing:
                            await publish_event(routing_key, body, exchange=exchange)

                    log.info(
                        "message_processed",
                        consumer=spec.name,
                        queue=spec.queue.name,
                        correlation_id=correlation_id,
                    )
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
        except Exception as exc:  # сообщение уже nack'нуто / отправлено в DLQ
            try:
                import sentry_sdk
                sentry_sdk.set_tag("correlation_id", correlation_id)
                sentry_sdk.capture_exception(exc)
            except Exception:
                pass
            log.exception(
                "message_processing_failed",
                consumer=spec.name,
                queue=spec.queue.name,
                redelivered=message.redelivered,
                error=str(exc),
                correlation_id=correlation_id,
            )
        finally:
            structlog.contextvars.clear_contextvars()
            reset_correlation_id(token)

    return on_message

'''
base = base[:proc_start] + new_processor + base[proc_end:]
base = base.replace(
    '    logging.basicConfig(level=logging.INFO,\n                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")\n',
    '    setup_logging()\n    setup_sentry()\n    setup_tracing(service_name=f"sirius-{spec.name}-worker")\n',
)
write("app/workers/base.py", base)


# ---------------------------------------------------------------------------
# Convert handler print() messages to structured event logs (business logic unchanged).
# ---------------------------------------------------------------------------
handlers = read("app/workers/handlers.py")
if "import structlog" not in handlers:
    handlers = replace_once(
        handlers,
        "import uuid\n",
        "import uuid\nimport structlog\n\nlog = structlog.get_logger(\"workers.handlers\")\n",
        "логгер в app/workers/handlers.py",
    )
replacements = {
    'print(f"[Kitchen] Дубликат события {event_id} — пропускаем")': 'log.info("duplicate_event_skipped", consumer=KITCHEN, event_id=event_id)',
    'print(f"[Kitchen] Заказ {order_id} уже на кухне — пропускаем")': 'log.info("order_already_in_kitchen", order_id=order_id)',
    'print(f"[Kitchen] Принят заказ {order_id}")': 'log.info("kitchen_order_accepted", order_id=order_id)',
    'print(f"[Delivery] Дубликат события {event_id} — пропускаем")': 'log.info("duplicate_event_skipped", consumer=DELIVERY, event_id=event_id)',
    'print(f"[Delivery] Для заказа {order_id} доставка уже создана")': 'log.info("delivery_already_created", order_id=order_id)',
    'print(f"[Delivery] Нет свободного курьера для заказа {order_id} → DeliveryFailed")': 'log.warning("delivery_failed_no_courier", order_id=order_id)',
    'print(f"[Delivery] Подготовка доставки для заказа {order_id}, курьер {courier_id}")': 'log.info("delivery_prepared", order_id=order_id, courier_id=courier_id)',
    'print(f"[Saga] Дубликат события {event_id} — компенсация уже выполнена")': 'log.info("saga_duplicate_skipped", event_id=event_id)',
    'print(f"[Saga] Заказ {order_id} в статусе \'{order.status}\' — компенсация не нужна")': 'log.info("saga_compensation_not_needed", order_id=order_id, status=order.status)',
    'print(f"[Saga] Заказ {order_id} отменён, клиенту {order.user_id} возвращено {amount:.2f}")': 'log.info("saga_order_cancelled_refund", order_id=order_id, user_id=order.user_id, refunded=amount)',
}
for old, new in replacements.items():
    if old in handlers:
        handlers = handlers.replace(old, new)
write("app/workers/handlers.py", handlers)


# ---------------------------------------------------------------------------
# Prometheus scrape config, Grafana provisioning and dashboard.
# ---------------------------------------------------------------------------
write("prometheus/prometheus.yml", r'''global:
  scrape_interval: 5s
  evaluation_interval: 5s

scrape_configs:
  - job_name: "sirius_app"
    metrics_path: /metrics
    static_configs:
      - targets: ["host.docker.internal:8000"]

  - job_name: "rabbitmq"
    metrics_path: /metrics/detailed
    params:
      family: ["queue_coarse_metrics"]
      vhost: ["/"]
    static_configs:
      - targets: ["rabbitmq:15692"]

  - job_name: "redis"
    static_configs:
      - targets: ["redis-exporter:9121"]
''')

write("grafana/provisioning/datasources/prometheus.yml", r'''apiVersion: 1

datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
''')

write("grafana/provisioning/dashboards/provider.yml", r'''apiVersion: 1

providers:
  - name: "Sirius dashboards"
    orgId: 1
    folder: "Sirius.Еда"
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /var/lib/grafana/dashboards
''')

panels = [
    {
        "id": 1, "type": "timeseries", "title": "HTTP RPS",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "targets": [{"refId": "A", "expr": "sum(rate(http_requests_total[1m]))", "legendFormat": "requests/sec"}],
        "fieldConfig": {"defaults": {"unit": "reqps"}, "overrides": []}, "options": {"legend": {"showLegend": True}, "tooltip": {"mode": "single"}},
    },
    {
        "id": 2, "type": "timeseries", "title": "HTTP latency p95",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "targets": [{"refId": "A", "expr": 'histogram_quantile(0.95, sum by (le) (rate(sirius_menu_items_request_duration_seconds_bucket[1m])))', "legendFormat": "p95"}],
        "fieldConfig": {"defaults": {"unit": "s"}, "overrides": []}, "options": {"legend": {"showLegend": True}, "tooltip": {"mode": "single"}},
    },
    {
        "id": 3, "type": "timeseries", "title": "HTTP 5xx errors/sec",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "targets": [{"refId": "A", "expr": 'sum(rate(http_requests_total{status="5xx"}[1m]))', "legendFormat": "5xx/sec"}],
        "fieldConfig": {"defaults": {"unit": "reqps"}, "overrides": []}, "options": {"legend": {"showLegend": True}, "tooltip": {"mode": "single"}},
    },
    {
        "id": 4, "type": "timeseries", "title": "RabbitMQ: kitchen_queue depth",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "targets": [{"refId": "A", "expr": 'rabbitmq_detailed_queue_messages{queue="kitchen_queue"}', "legendFormat": "kitchen_queue"}],
        "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []}, "options": {"legend": {"showLegend": True}, "tooltip": {"mode": "single"}},
    },
    {
        "id": 5, "type": "timeseries", "title": "Redis cache hit rate",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 16},
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "targets": [{"refId": "A", "expr": '(sum(rate(redis_keyspace_hits_total[5m])) / clamp_min(sum(rate(redis_keyspace_hits_total[5m])) + sum(rate(redis_keyspace_misses_total[5m])), 1e-9)) * 100', "legendFormat": "hit rate %"}],
        "fieldConfig": {"defaults": {"unit": "percent", "min": 0, "max": 100}, "overrides": []}, "options": {"legend": {"showLegend": True}, "tooltip": {"mode": "single"}},
    },
    {
        "id": 6, "type": "stat", "title": "Prometheus targets UP",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 16},
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "targets": [{"refId": "A", "expr": "sum(up)", "legendFormat": "UP targets"}],
        "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []}, "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "orientation": "auto", "textMode": "auto", "colorMode": "value", "graphMode": "area", "justifyMode": "auto"},
    },
]
dashboard = {
    "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"}]},
    "editable": True, "fiscalYearStartMonth": 0, "graphTooltip": 0, "id": None,
    "links": [], "liveNow": False, "panels": panels,
    "refresh": "5s", "schemaVersion": 39, "tags": ["sirius", "observability"],
    "templating": {"list": []}, "time": {"from": "now-15m", "to": "now"},
    "timepicker": {}, "timezone": "browser", "title": "Сириус.Еда — Observability",
    "uid": "sirius-observability", "version": 1,
}
write("grafana/dashboards/sirius-observability.json", json.dumps(dashboard, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# docker-compose.yml — extend existing services without replacing them.
# ---------------------------------------------------------------------------
compose = read("docker-compose.yml")
# Enable the RabbitMQ Prometheus plugin and publish its metrics port.
rabbit_match = re.search(r"(?ms)^  rabbitmq:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|^volumes:\n)", compose)
if not rabbit_match:
    raise SystemExit("Не найден сервис rabbitmq в docker-compose.yml")
rabbit_block = rabbit_match.group(0)
if "rabbitmq_prometheus" not in rabbit_block:
    container_line = re.search(r"(?m)^    container_name:.*$", rabbit_block)
    if not container_line:
        raise SystemExit("Не найден container_name у RabbitMQ; не могу безопасно включить Prometheus plugin")
    insert_at = container_line.end()
    rabbit_block = rabbit_block[:insert_at] + (
        '\n    command: >\n'
        '      sh -c "rabbitmq-plugins enable --offline rabbitmq_prometheus && rabbitmq-server"'
    ) + rabbit_block[insert_at:]
if not re.search(r"(?m)^\s*- [\"']?15692:15692", rabbit_block):
    port_line = re.search(r"(?m)^\s*- [\"']?15672:15672[^\n]*$", rabbit_block)
    if not port_line:
        raise SystemExit("Не найден порт 15672 RabbitMQ в docker-compose.yml")
    rabbit_block = rabbit_block[:port_line.end()] + '\n      - "15692:15692"  # Prometheus metrics' + rabbit_block[port_line.end():]
compose = compose[:rabbit_match.start()] + rabbit_block + compose[rabbit_match.end():]

services_block = dedent('''
  prometheus:
    image: prom/prometheus:latest
    container_name: sirius_prometheus
    ports:
      - "9090:9090"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    depends_on:
      - rabbitmq
      - redis-exporter
    restart: unless-stopped

  redis-exporter:
    image: oliver006/redis_exporter:latest
    container_name: sirius_redis_exporter
    environment:
      REDIS_ADDR: redis://redis:6379
    depends_on:
      - redis
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    container_name: sirius_grafana
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    depends_on:
      - prometheus
    restart: unless-stopped

  jaeger:
    image: jaegertracing/all-in-one:1.57
    container_name: sirius_jaeger
    environment:
      COLLECTOR_OTLP_ENABLED: "true"
    ports:
      - "16686:16686"
      - "4317:4317"
      - "4318:4318"
    restart: unless-stopped
''').strip()
services_block = "\n".join("  " + line if line else "" for line in services_block.splitlines())
if not re.search(r"(?m)^  prometheus:\s*$", compose):
    volumes_anchor = re.search(r"(?m)^volumes:\s*$", compose)
    if not volumes_anchor:
        raise SystemExit("Не найден верхнеуровневый volumes: в docker-compose.yml")
    compose = compose[:volumes_anchor.start()] + services_block + "\n" + compose[volumes_anchor.start():]
write("docker-compose.yml", compose)


# ---------------------------------------------------------------------------
# start.sh and .gitignore.
# ---------------------------------------------------------------------------
start_script = read("start.sh") if (ROOT / "start.sh").exists() else ""
if start_script:
    start_script = start_script.replace(
        "docker compose up -d db redis rabbitmq > /dev/null",
        "docker compose up -d db redis rabbitmq prometheus redis-exporter grafana jaeger > /dev/null",
    )
    start_script = start_script.replace(
        "start api uvicorn app.main:app --reload",
        "start api uvicorn app.main:app --reload --host 0.0.0.0",
    )
    write("start.sh", start_script)

ignore = read(".gitignore") if (ROOT / ".gitignore").exists() else ""
if ".backups/" not in ignore.splitlines():
    ignore = ignore.rstrip() + "\n.backups/\n"
write(".gitignore", ignore)


# ---------------------------------------------------------------------------
# Example configuration and user-facing usage notes.
# ---------------------------------------------------------------------------
write("observability.env.example", r'''# Скопируйте нужные строки в .env. DSN выдаётся в настройках проекта Sentry.
OTEL_ENABLED=true
OTEL_SERVICE_NAME=sirius-app
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Необязательно: Sentry включается только после добавления DSN.
SENTRY_DSN=
SENTRY_ENVIRONMENT=development
SENTRY_TRACES_SAMPLE_RATE=0.0

# Необязательно: временный endpoint для проверки Sentry в DEBUG-режиме.
# После проверки верните false.
OBSERVABILITY_TEST_ENDPOINT=false
''')

readme = read("README.md")
if "<!-- lab9-observability -->" not in readme:
    readme += r'''

---
<!-- lab9-observability -->
# Практическая работа № 9 — Observability

В проект добавлены correlation ID, структурированные JSON-логи, Prometheus,
Grafana, метрики RabbitMQ/Redis, Sentry (опционально) и OpenTelemetry с Jaeger.
Существующая бизнес-логика заказа и Saga не меняется.

## Запуск

```bash
source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d db redis rabbitmq prometheus redis-exporter grafana jaeger
alembic upgrade head
```

Запускайте API с адресом `0.0.0.0`, чтобы Prometheus из Docker мог опрашивать
процесс на хосте:

```bash
uvicorn app.main:app --reload --host 0.0.0.0
```

Consumer кухни (отдельный терминал):

```bash
python -m app.workers.kitchen_consumer
```

При запуске `./start.sh` API и workers поднимаются вместе, а observability-
инфраструктура запускается через Docker Compose.

## Correlation ID и расследование заказа

Проект публикует событие `order.paid` в RabbitMQ при вызове
`POST /orders/{order_id}/pay`, а не при создании заказа. Поэтому один и тот же
`X-Correlation-ID` нужно передать в запрос создания и в запрос оплаты.
Получите access token через `POST /auth/login`, затем выполните:

```bash
export TOKEN="<access_token>"
export CID="demo-42"

# Создание заказа (подставьте существующий item_id и количество).
curl -i -X POST http://127.0.0.1:8000/orders/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: $CID" \
  -d '{"item_id": 1, "quantity": 1}'

# Из ответа возьмите order_id.
export ORDER_ID="<order_id из предыдущего ответа>"

# Оплата публикует order.paid; consumer кухни получает тот же correlation ID.
curl -i -X POST "http://127.0.0.1:8000/orders/$ORDER_ID/pay" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Correlation-ID: $CID"
```

В обоих HTTP-ответах будет `X-Correlation-ID`. В логах API и consumer'а найдите
его так (при запуске через `./start.sh`):

```bash
jq 'select(.correlation_id == "demo-42")' logs/api.log
jq 'select(.correlation_id == "demo-42")' logs/kitchen.log
```

При ручном запуске процессов JSON-логи выводятся в соответствующие терминалы.
RabbitMQ передаёт `X-Correlation-ID` в AMQP headers, а `traceparent` — для
связи span'ов OpenTelemetry.

## Интерфейсы

- Prometheus: <http://localhost:9090/targets> — `sirius_app`, `rabbitmq` и `redis` должны быть `UP`.
- Grafana: <http://localhost:3000> — логин/пароль `admin` / `admin`; datasource и дашборд создаются автоматически.
- Jaeger: <http://localhost:16686> — сервис `sirius-app`, поиск trace после оплаты заказа.
- RabbitMQ Management: <http://localhost:15672> — `sirius` / `sirius`.
- Метрики приложения: <http://localhost:8000/metrics>.

Дашборд `Сириус.Еда — Observability` содержит RPS запросов создания заказа,
latency p95 для `GET /menu/items`, ошибки 5xx, длину `kitchen_queue`, Redis
cache hit rate и количество доступных targets.

## Sentry (дополнительный уровень)

Скопируйте DSN проекта Sentry в `.env` как `SENTRY_DSN=...`, перезапустите API
(и worker, если хотите собирать ошибки consumer'ов). Для ручной проверки можно
временно включить `OBSERVABILITY_TEST_ENDPOINT=true` при `DEBUG=true`, затем
вызвать `GET /observability/test-error` с `X-Correlation-ID: demo-42`.
После проверки отключите endpoint обратно.

## OpenTelemetry (10 баллов)

OpenTelemetry включён по умолчанию. По умолчанию OTLP exporter отправляет span'ы
в `http://localhost:4317` (Jaeger из Compose). Для окружения с другим адресом
задайте `OTEL_EXPORTER_OTLP_ENDPOINT`. На пути оплаты видны HTTP span, span
публикации RabbitMQ и consumer span кухни. В Jaeger consumer'ы имеют отдельные
service name: `sirius-kitchen-worker`, `sirius-delivery-worker` и
`sirius-order_saga-worker`; API по умолчанию называется `sirius-app`.
'''
    write("README.md", readme)

print("Observability files and integrations have been created/updated.")
PY

# Убедимся, что start.sh исполняемый, если он есть.
if [[ -f start.sh ]]; then chmod +x start.sh; fi

# Проверяем синтаксис обновлённых Python-файлов без запуска приложения.
python3 -m py_compile \
  app/main.py \
  app/core/logging.py \
  app/core/correlation.py \
  app/core/metrics.py \
  app/core/sentry.py \
  app/core/tracing.py \
  app/core/rabbitmq.py \
  app/workers/base.py \
  app/workers/handlers.py

if command -v docker >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    echo "==> Проверка docker-compose.yml..."
    docker compose config -q
  fi
fi

echo
echo "Готово: observability добавлена. Резервная копия: $BACKUP_DIR"
echo "Следующий шаг: source .venv/bin/activate && pip install -r requirements.txt"
echo "Затем: docker compose up -d db redis rabbitmq prometheus redis-exporter grafana jaeger"
echo "Проверяйте Prometheus: http://localhost:9090/targets | Grafana: http://localhost:3000 | Jaeger: http://localhost:16686"
