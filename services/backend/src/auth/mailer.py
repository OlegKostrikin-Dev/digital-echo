from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)

# Отдельный connect: при «молчащем» файрволе/IPv6 иначе висим десятки секунд без ошибки.
_RESEND_TIMEOUT = httpx.Timeout(45.0, connect=12.0, pool=8.0)


def send_resend_email(to: str, subject: str, html: str) -> None:
    key = os.getenv("RESEND_API_KEY", "").strip()
    if not key:
        raise RuntimeError("RESEND_API_KEY не задан — письмо не отправлено.")
    from_email = os.getenv("RESEND_FROM", "onboarding@resend.dev").strip()
    log.info("Resend: POST https://api.resend.com/emails to=%s from=%s", to, from_email)
    try:
        with httpx.Client(timeout=_RESEND_TIMEOUT) as client:
            r = client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_email,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
    except httpx.ConnectError as e:
        log.exception("Resend: нет соединения с api.resend.com")
        raise RuntimeError(
            "Не удалось подключиться к api.resend.com (сеть/DNS/VPN). "
            'Проверьте из контейнера: curl -sS -o /dev/null -w "%{http_code}" https://api.resend.com'
        ) from e
    except httpx.TimeoutException as e:
        log.exception("Resend: таймаут HTTP")
        raise RuntimeError(
            "Таймаут ответа Resend. Проверьте доступ в интернет из Docker и переменные RESEND_*."
        ) from e
    log.info("Resend: ответ HTTP %s", r.status_code)
    if r.status_code >= 400:
        raw = r.text
        try:
            err_json = r.json()
            api_msg = str(err_json.get("message", "") or "")
            low = api_msg.lower()
            if r.status_code == 403 and (
                "only send testing emails" in low or "verify a domain" in low
            ):
                raise RuntimeError(
                    "Resend (тестовый режим): в запросе всё ещё используется отправитель "
                    "onboarding@resend.dev — с ним письма можно слать только на email владельца аккаунта. "
                    "Если домен уже подтверждён в Resend, в .env задайте RESEND_FROM=... "
                    "(например noreply@example.com) и перезапустите backend. "
                    "См. https://resend.com/domains"
                ) from None
        except RuntimeError:
            raise
        except Exception:
            pass
        raise RuntimeError(f"Resend HTTP {r.status_code}: {raw}")
