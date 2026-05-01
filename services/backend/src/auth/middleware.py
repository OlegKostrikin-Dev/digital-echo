from __future__ import annotations

import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import service
from .routes import COOKIE_NAME
from .jwt_utils import decode_token


class AccessGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        val = os.getenv("ENABLE_ACCESS_GATE", "1").lower()
        if val in ("0", "false", "no", "off"):
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api"):
            return await call_next(request)

        if path.startswith("/api/auth") or path == "/api/health":
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Требуется вход по коду доступа."},
            )
        payload = decode_token(token)
        if not payload or payload.get("role") not in ("admin", "guest"):
            return JSONResponse(
                status_code=401,
                content={"detail": "Сессия недействительна. Войдите снова."},
            )

        if payload.get("role") == "guest" and not service.guest_session_allowed(
            str(payload["sub"])
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "Доступ отозван администратором."},
            )

        return await call_next(request)
