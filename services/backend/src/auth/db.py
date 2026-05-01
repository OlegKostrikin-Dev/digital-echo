from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

_engine = None
_SessionLocal = None


def _apply_auth_migrations(engine) -> None:
    """SQLite: новые колонки, слияние дубликатов guest_email, уникальный индекс."""
    with engine.begin() as conn:
        info = conn.execute(text("PRAGMA table_info(invite)")).fetchall()
        if not info:
            return
        cols = {row[1] for row in info}
        if "blocked" not in cols:
            conn.execute(
                text("ALTER TABLE invite ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
            )
        conn.execute(
            text(
                "UPDATE invite SET guest_email = lower(trim(guest_email)) "
                "WHERE guest_email IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "DELETE FROM invite WHERE id NOT IN "
                "(SELECT MAX(id) FROM invite GROUP BY guest_email)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_invite_guest_email "
                "ON invite (guest_email)"
            )
        )
        conn.execute(text("UPDATE invite SET consumed_at = NULL"))


def get_auth_db_path() -> Path:
    raw = os.getenv("AUTH_SQLITE_PATH", "/app/data/auth.sqlite")
    p = Path(raw)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_engine():
    global _engine
    if _engine is None:
        path = get_auth_db_path()
        _engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(_engine)
        _apply_auth_migrations(_engine)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            class_=Session,
            expire_on_commit=False,
        )
    return _SessionLocal


@contextmanager
def session_scope():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
