"""GraphState — потокобезопасный держатель состояния расчёта.

Хранит последний прогон в памяти процесса. Один процесс = одна копия графа.
Если нужно пересчитать — клиент отправляет POST /api/recompute, который
запускает фон в executor (uvicorn-worker остаётся отзывчивым).

Поддерживает два режима:
- live: пересчёт читает MySQL/VoltDB по запросу (полный функционал);
- readonly snapshot: читает файл-снимок в фоне после старта ASGI и не позволяет пересчёт
  (используется на демо-серверах без доступа к источникам данных).

Управляется переменными окружения:
- SNAPSHOT_PATH — если задан и файл существует, состояние загрузится из него
  в фоне (см. bootstrap_storage в lifespan), чтобы /api/auth отвечал сразу.
- READONLY_SNAPSHOT=1 — запретить /api/recompute и /api/save-snapshot.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import networkx as nx

from .core.engine import compute_state
from .core.snapshot import load_snapshot, save_snapshot

log = logging.getLogger(__name__)


class GraphState:
    """Состояние одного in-memory прогона."""

    def __init__(self) -> None:
        self._graph: Optional[nx.DiGraph] = None
        self._kz: dict[str, float] = {}
        self._meta: dict[str, Any] = {}
        self._days: Optional[int] = None
        self._started_at: Optional[str] = None
        self._finished_at: Optional[str] = None
        self._duration: Optional[float] = None
        self._status: str = "idle"  # idle | computing | ready | error
        self._error: Optional[str] = None
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._snapshot_path: Optional[Path] = None
        self._readonly: bool = bool(int(os.getenv("READONLY_SNAPSHOT", "0") or "0"))
        self._snapshot_saved_at: Optional[str] = None

        snapshot_path = os.getenv("SNAPSHOT_PATH")
        self._snapshot_path = Path(snapshot_path) if snapshot_path else None

    def bootstrap_storage(self) -> None:
        """Загрузить pickle-снимок после того, как ASGI-сервер уже слушает порт.

        Не вызывать из __init__: синхронное чтение большого файла блокирует импорт
        и старт uvicorn — запросы (в том числе POST /api/auth/...) висят без ответа.
        """
        if not self._snapshot_path:
            return
        log.info("Фоновая загрузка снимка графа: %s", self._snapshot_path)
        if self._snapshot_path.exists():
            self._load_from_snapshot()
        elif self._readonly:
            log.error(
                "READONLY_SNAPSHOT включён, но snapshot %s не найден — "
                "сервис не сможет отдать данные",
                self._snapshot_path,
            )

    @property
    def readonly(self) -> bool:
        return self._readonly

    def _load_from_snapshot(self) -> None:
        assert self._snapshot_path is not None
        try:
            payload = load_snapshot(self._snapshot_path)
        except Exception as exc:  # noqa: BLE001
            log.exception("Не удалось загрузить snapshot: %s", exc)
            self._error = f"snapshot load failed: {exc}"
            self._status = "error"
            return
        self._graph = payload["graph"]
        self._kz = payload["kz"]
        self._meta = payload["meta"]
        self._days = self._meta.get("days")
        self._snapshot_saved_at = payload.get("saved_at")
        self._started_at = self._snapshot_saved_at
        self._finished_at = self._snapshot_saved_at
        self._status = "ready"
        log.info(
            "graph state loaded from snapshot: nodes=%d edges=%d",
            self._graph.number_of_nodes(),
            self._graph.number_of_edges(),
        )

    # ------------------------------------------------------------ accessors
    @property
    def graph(self) -> nx.DiGraph:
        if self._graph is None:
            raise RuntimeError("Граф ещё не построен. Запустите POST /api/recompute.")
        return self._graph

    @property
    def kz(self) -> dict[str, float]:
        if not self._kz:
            raise RuntimeError("kz_content ещё не рассчитан.")
        return self._kz

    @property
    def is_ready(self) -> bool:
        return self._status == "ready"

    @property
    def is_computing(self) -> bool:
        return self._status == "computing"

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "days": self._days,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "duration_seconds": self._duration,
            "error": self._error,
            "meta": self._meta if self._status == "ready" else None,
            "readonly": self._readonly,
            "snapshot_saved_at": self._snapshot_saved_at,
        }

    def save_to_disk(self, path: Optional[str | Path] = None) -> Path:
        if self._graph is None or not self._kz:
            raise RuntimeError("Граф не готов — нечего сохранять.")
        target = Path(path) if path else self._snapshot_path
        if target is None:
            raise RuntimeError("SNAPSHOT_PATH не задан и path не передан.")
        return save_snapshot(target, self._graph, self._kz, self._meta)

    # ----------------------------------------------------------- recompute
    async def recompute(self, days: int, force: bool = False) -> dict[str, Any]:
        if self._readonly:
            raise RuntimeError(
                "Сервис запущен в режиме READONLY_SNAPSHOT — пересчёт недоступен."
            )

        # Если уже считается — возвращаем текущее состояние, не запускаем второй раз
        if self._status == "computing":
            return self.snapshot()

        # Если уже посчитано на тех же параметрах — возврат без перерасчёта
        if not force and self._status == "ready" and self._days == days:
            return self.snapshot()

        async with self._lock:
            # Проверим ещё раз внутри lock — на случай гонки
            if self._status == "computing":
                return self.snapshot()
            if not force and self._status == "ready" and self._days == days:
                return self.snapshot()

            self._status = "computing"
            self._days = days
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._finished_at = None
            self._duration = None
            self._error = None
            self._meta = {}

            loop = asyncio.get_running_loop()
            t0 = time.perf_counter()
            try:
                state = await loop.run_in_executor(
                    self._executor,
                    compute_state,
                    days,
                )
                self._graph = state["graph"]
                self._kz = state["kz"]
                self._meta = state["meta"]
                self._status = "ready"
            except Exception as exc:  # noqa: BLE001
                self._error = f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
                self._status = "error"
            finally:
                self._duration = round(time.perf_counter() - t0, 2)
                self._finished_at = datetime.now(timezone.utc).isoformat()

            return self.snapshot()


# Глобальный singleton — простота прототипа важнее чистоты DI.
_state = GraphState()


def get_state() -> GraphState:
    return _state
