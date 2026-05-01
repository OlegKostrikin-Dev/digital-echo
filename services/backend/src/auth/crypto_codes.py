from __future__ import annotations

import hashlib
import secrets


def norm_email(email: str) -> str:
    return email.strip().lower()


def new_salt() -> str:
    return secrets.token_hex(16)


def hash_code(secret: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{secret}".encode("utf-8")).hexdigest()


def verify_code(secret: str, salt: str, digest: str) -> bool:
    return secrets.compare_digest(hash_code(secret, salt), digest)


def new_guest_code() -> str:
    """6-значный числовой код приглашения."""
    return f"{secrets.randbelow(1_000_000):06d}"


def new_admin_code() -> str:
    """6-значный OTP для админа."""
    return f"{secrets.randbelow(1_000_000):06d}"
