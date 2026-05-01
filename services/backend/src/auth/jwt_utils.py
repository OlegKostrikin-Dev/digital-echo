from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt

ALG = "HS256"


def issue_token(email: str, role: str) -> str:
    secret = os.environ.get("AUTH_JWT_SECRET")
    if not secret or len(secret) < 16:
        raise RuntimeError("AUTH_JWT_SECRET не задан или слишком короткий.")
    days_guest = int(os.getenv("AUTH_SESSION_DAYS_GUEST", "7"))
    days_admin = int(os.getenv("AUTH_SESSION_DAYS_ADMIN", "7"))
    days = days_admin if role == "admin" else days_guest
    exp = datetime.now(timezone.utc) + timedelta(days=days)
    payload = {"sub": email, "role": role, "exp": exp}
    return jwt.encode(payload, secret, algorithm=ALG)


def decode_token(token: str) -> dict | None:
    secret = os.environ.get("AUTH_JWT_SECRET")
    if not secret:
        return None
    try:
        return jwt.decode(token, secret, algorithms=[ALG])
    except jwt.PyJWTError:
        return None
