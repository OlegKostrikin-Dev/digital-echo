from __future__ import annotations

import logging
import os
import re
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator

from . import service
from .jwt_utils import decode_token

log = logging.getLogger(__name__)

COOKIE_NAME = "dec_session"


def _cookie_kwargs() -> dict:
    secure = os.getenv("AUTH_COOKIE_SECURE", "0").lower() in ("1", "true", "yes")
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": secure,
    }


def _set_session_cookie(response: Response, token: str) -> None:
    max_age = int(os.getenv("AUTH_COOKIE_MAX_AGE_SEC", str(7 * 24 * 3600)))
    response.set_cookie(value=token, max_age=max_age, **_cookie_kwargs())


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(**_cookie_kwargs())


def get_optional_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("role") not in ("admin", "guest"):
        return None
    if payload.get("role") == "guest" and not service.guest_session_allowed(
        str(payload["sub"])
    ):
        return None
    return {"email": payload["sub"], "role": payload["role"]}


def require_admin(request: Request) -> str:
    u = get_optional_user(request)
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Нужны права администратора.")
    return str(u["email"])


router = APIRouter(prefix="/auth", tags=["auth"])


class AdminOtpRequest(BaseModel):
    email: EmailStr


class AdminOtpVerify(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=12)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_admin_code(cls, v: Any) -> str:
        """Цифры из вставки («Код: 123 456», неразрывный пробел и т.д.)."""
        if v is None:
            return ""
        s = str(v).replace("\u00a0", " ").strip()
        return re.sub(r"\D", "", s)


class GuestVerify(BaseModel):
    code: str = Field(..., min_length=6, max_length=32)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_guest_code(cls, v: Any) -> str:
        if v is None:
            return ""
        s = str(v).replace("\u00a0", " ").strip()
        return re.sub(r"\D", "", s)


class InviteCreate(BaseModel):
    guest_email: EmailStr


class InviteBlockedBody(BaseModel):
    blocked: bool


@router.post("/admin/request-otp")
def admin_request_otp(body: AdminOtpRequest) -> dict:
    log.info("POST /api/auth/admin/request-otp email=%s", body.email)
    try:
        service.request_admin_otp(body.email)
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {
        "ok": True,
        "message": (
            "Запрос принят. Если этот email зарегистрирован как администратор, "
            "на почту отправлен код — проверьте «Спам». Затем введите код ниже. "
            "Если письма нет, возможно, адрес указан неверно."
        ),
    }


@router.post("/admin/verify-otp")
def admin_verify_otp(body: AdminOtpVerify, response: Response) -> dict:
    try:
        token = service.verify_admin_otp(body.email, body.code)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    _set_session_cookie(response, token)
    return {"ok": True, "role": "admin"}


@router.post("/guest/verify")
def guest_verify(body: GuestVerify, response: Response) -> dict:
    try:
        token = service.verify_guest_code(body.code)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    _set_session_cookie(response, token)
    return {"ok": True, "role": "guest"}


@router.get("/me")
def auth_me(request: Request) -> dict:
    u = get_optional_user(request)
    if not u:
        return {"authenticated": False}
    return {"authenticated": True, **u}


@router.post("/logout")
def auth_logout(response: Response) -> dict:
    _clear_session_cookie(response)
    return {"ok": True}


@router.post("/admin/invites")
def admin_create_invite(
    body: InviteCreate,
    admin_email: Annotated[str, Depends(require_admin)],
) -> dict:
    try:
        service.create_invite(admin_email, body.guest_email)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"ok": True}


@router.get("/admin/invites")
def admin_list_invites(
    admin_email: Annotated[str, Depends(require_admin)],
) -> dict:
    return {"items": service.list_invites(admin_email)}


@router.patch("/admin/invites/{invite_id}")
def admin_set_invite_blocked(
    invite_id: Annotated[int, Path(ge=1)],
    body: InviteBlockedBody,
    admin_email: Annotated[str, Depends(require_admin)],
) -> dict:
    try:
        service.set_invite_blocked(admin_email, invite_id, body.blocked)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"ok": True}
