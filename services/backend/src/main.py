"""digital-echo-core FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router as api_router
from .auth.middleware import AccessGateMiddleware
from .auth.routes import router as auth_router
from .deps import get_state


def _configure_auth_logging() -> None:
    """Uvicorn не всегда поднимает root до INFO — дублируем stderr для auth.*."""
    fmt = logging.Formatter("%(levelname)s [%(name)s] %(message)s")
    for name in ("auth", "auth.service", "auth.mailer", "auth.routes"):
        log = logging.getLogger(name)
        if log.handlers:
            continue
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(fmt)
        log.addHandler(h)
        log.setLevel(logging.INFO)
        log.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Загрузку snapshot не await — иначе порт не откроется, пока не допарсится pickle.
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, get_state().bootstrap_storage)
    yield


def create_app() -> FastAPI:
    _configure_auth_logging()
    app = FastAPI(
        title="digital-echo-core",
        description=(
            "Аналитический движок для расчёта индекса казахстанского содержания (КС) "
            "на основе графа B2B-транзакций."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    cors_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000",
    ).split(",")
    app.add_middleware(AccessGateMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router, prefix="/api")
    app.include_router(api_router)

    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {
            "service": "digital-echo-core",
            "docs_url": "/docs",
            "openapi_url": "/openapi.json",
            "api_root": "/api",
        }

    return app


app = create_app()
