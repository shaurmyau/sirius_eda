"""Необязательная интеграция Sentry; активируется переменной SENTRY_DSN."""
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
