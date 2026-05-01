from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .crypto_codes import (
    hash_code,
    new_admin_code,
    new_guest_code,
    new_salt,
    norm_email,
    verify_code,
)
from .db import session_scope
from .jwt_utils import issue_token
from .mailer import send_resend_email
from .models import AdminOTPRow, InviteRow

log = logging.getLogger(__name__)


def _dt_as_utc_aware(dt: datetime) -> datetime:
    """SQLite часто отдаёт naive UTC; сравнение с now(tz=UTC) иначе даёт TypeError."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

RATE_WINDOW_SEC = 900
RATE_MAX = 5

_otp_buckets: dict[str, list[float]] = defaultdict(list)


def _rate_ok(key: str) -> bool:
    now = time.monotonic()
    bucket = _otp_buckets[key]
    bucket[:] = [t for t in bucket if now - t < RATE_WINDOW_SEC]
    if len(bucket) >= RATE_MAX:
        return False
    bucket.append(now)
    return True


def admin_allowlist() -> set[str]:
    raw = os.getenv(
        "ADMIN_EMAILS",
        "okostrikin@gmail.com,anvar.sadykov@gmail.com",
    )
    return {norm_email(e) for e in raw.split(",") if e.strip()}


def request_admin_otp(email: str) -> None:
    """Отправляет OTP только если email в белом списке. Иначе no-op (без утечки)."""
    email_n = norm_email(email)
    if email_n not in admin_allowlist():
        log.info("admin OTP: %s не в ADMIN_EMAILS, ответ без отправки", email_n)
        return
    if not _rate_ok(f"admin_otp:{email_n}"):
        raise ValueError("Слишком много запросов кода. Попробуйте через 15 минут.")

    log.info("admin OTP: сохранение кода и вызов Resend для %s", email_n)
    code = new_admin_code()
    salt = new_salt()
    chash = hash_code(code, salt)
    ttl = int(os.getenv("ADMIN_OTP_TTL_MINUTES", "15"))
    exp = datetime.now(timezone.utc) + timedelta(minutes=ttl)
    with session_scope() as db:
        db.add(
            AdminOTPRow(
                email=email_n,
                code_hash=chash,
                salt=salt,
                expires_at=exp,
            )
        )
        db.commit()

    send_resend_email(
        to=email_n,
        subject="Код входа — digital-echo-core (админ)",
        html=(
            f"<p>Код для входа в админ-консоль:</p>"
            f"<p style=\"font-size:1.5rem\"><strong>{code}</strong></p>"
            f"<p>Срок действия кода: {ttl} мин.</p>"
        ),
    )
    log.info("admin OTP: письмо отправлено через Resend для %s", email_n)


def verify_admin_otp(email: str, code: str) -> str:
    email_n = norm_email(email)
    if email_n not in admin_allowlist():
        raise PermissionError("Неверный email или код.")
    now = datetime.now(timezone.utc)
    stmt = (
        select(AdminOTPRow)
        .where(AdminOTPRow.email == email_n)
        .where(AdminOTPRow.consumed_at.is_(None))
        .where(AdminOTPRow.expires_at > now)
        .order_by(AdminOTPRow.id.desc())
        .limit(1)
    )
    with session_scope() as db:
        row = db.scalars(stmt).first()
        if row is None or not verify_code(code.strip(), row.salt, row.code_hash):
            raise PermissionError("Неверный или просроченный код.")
        row.consumed_at = now
        db.commit()
    return issue_token(email_n, "admin")


def create_invite(admin_email: str, guest_email: str) -> None:
    admin_n = norm_email(admin_email)
    guest_n = norm_email(guest_email)
    if admin_n not in admin_allowlist():
        raise PermissionError("Нет прав администратора.")
    if not guest_n or "@" not in guest_n:
        raise ValueError("Некорректный email гостя.")

    code = new_guest_code()
    salt = new_salt()
    chash = hash_code(code, salt)
    days = int(os.getenv("INVITE_VALID_DAYS", "7"))
    exp = datetime.now(timezone.utc) + timedelta(days=days)
    with session_scope() as db:
        stmt = select(InviteRow).where(InviteRow.guest_email == guest_n)
        row = db.scalars(stmt).first()
        if row:
            row.code_hash = chash
            row.salt = salt
            row.expires_at = exp
            row.created_by = admin_n
            row.blocked = False
        else:
            db.add(
                InviteRow(
                    guest_email=guest_n,
                    code_hash=chash,
                    salt=salt,
                    expires_at=exp,
                    created_by=admin_n,
                    blocked=False,
                )
            )
        db.commit()

    send_resend_email(
        to=guest_n,
        subject="Код доступа — digital-echo-core",
        html=(
            f"<p>Вам открыли доступ к демонстрации <strong>digital-echo-core</strong>.</p>"
            f"<p>Срок действия кода — <strong>{days}</strong> дн. с момента выдачи "
            f"(до {exp.strftime('%Y-%m-%d %H:%M')} UTC). За это время можно входить "
            f"несколько раз с тем же кодом.</p>"
            f"<p>Код доступа (только цифры, страница входа без email):</p>"
            f"<p style=\"font-size:1.25rem\"><strong>{code}</strong></p>"
        ),
    )


def norm_guest_code_input(code: str) -> str:
    s = str(code).replace("\u00a0", " ").strip()
    return re.sub(r"\D", "", s)


def verify_guest_code(code: str) -> str:
    """Вход по коду приглашения. Код действует до expires_at (срок с выдачи админом), не одноразовый."""
    code_clean = norm_guest_code_input(code)
    if len(code_clean) < 6:
        raise PermissionError("Неверный код или срок приглашения истёк.")
    now = datetime.now(timezone.utc)
    stmt = (
        select(InviteRow)
        .where(InviteRow.expires_at > now)
        .where(InviteRow.blocked.is_(False))
    )
    with session_scope() as db:
        rows = db.scalars(stmt).all()
        for row in rows:
            if verify_code(code_clean, row.salt, row.code_hash):
                return issue_token(row.guest_email, "guest")
    raise PermissionError("Неверный код, срок истёк, или доступ заблокирован.")


def guest_session_allowed(email: str) -> bool:
    """Сессия гостя: приглашение есть, не заблокировано, срок не истёк."""
    email_n = norm_email(email)
    now = datetime.now(timezone.utc)
    with session_scope() as db:
        row = db.scalars(
            select(InviteRow).where(InviteRow.guest_email == email_n)
        ).first()
        if row is None or row.blocked:
            return False
        if _dt_as_utc_aware(row.expires_at) <= now:
            return False
        return True


def set_invite_blocked(admin_email: str, invite_id: int, blocked: bool) -> None:
    admin_n = norm_email(admin_email)
    if admin_n not in admin_allowlist():
        raise PermissionError("Нет прав администратора.")
    with session_scope() as db:
        row = db.get(InviteRow, invite_id)
        if row is None:
            raise ValueError("Приглашение не найдено.")
        row.blocked = blocked
        db.commit()


def list_invites(_admin_email: str) -> list[dict]:
    """Список приглашений (без кодов). Право вызывающего уже проверено."""
    stmt = select(InviteRow).order_by(InviteRow.guest_email).limit(500)
    with session_scope() as db:
        rows = db.scalars(stmt).all()
    return [
        {
            "id": r.id,
            "guest_email": r.guest_email,
            "expires_at": r.expires_at.isoformat(),
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat(),
            "blocked": bool(r.blocked),
        }
        for r in rows
    ]
