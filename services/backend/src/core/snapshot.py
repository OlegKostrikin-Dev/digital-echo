"""Snapshot — сохранение/загрузка вычисленного состояния графа на диск.

Используется для развёртывания на демо-серверах, у которых нет доступа к
production MySQL/VoltDB. Полный pipeline (load_edges → build_graph →
enrich_with_voltdb → compute_kz_content) запускается один раз на машине,
имеющей доступ к источникам данных, результат сериализуется pickle'ом и
переносится на демо-сервер.

Формат:
    {
      "version": 1,
      "graph": <DiGraph>,                # включает атрибуты узлов и весы рёбер
      "kz": {tin: float},
      "meta": {...},                     # как в engine.compute_state
      "saved_at": "2026-04-30T15:00:00", # ISO-8601 UTC
    }
"""

from __future__ import annotations

import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx

log = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1


def save_snapshot(
    path: str | Path,
    graph: nx.DiGraph,
    kz: dict[str, float],
    meta: dict[str, Any],
) -> Path:
    """Сериализовать состояние в pickle-файл."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SNAPSHOT_VERSION,
        "graph": graph,
        "kz": kz,
        "meta": meta,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(p)
    log.info(
        "snapshot saved: path=%s nodes=%d edges=%d size=%.1f MB",
        p,
        graph.number_of_nodes(),
        graph.number_of_edges(),
        p.stat().st_size / 1e6,
    )
    return p


def load_snapshot(path: str | Path) -> dict[str, Any]:
    """Загрузить состояние из pickle-файла."""
    p = Path(path)
    with p.open("rb") as f:
        payload = pickle.load(f)
    version = payload.get("version")
    if version != SNAPSHOT_VERSION:
        raise ValueError(
            f"Несовместимая версия snapshot ({version!r}), "
            f"ожидается {SNAPSHOT_VERSION}"
        )
    if not isinstance(payload.get("graph"), nx.DiGraph):
        raise ValueError("snapshot.graph не является networkx.DiGraph")
    log.info(
        "snapshot loaded: path=%s nodes=%d edges=%d saved_at=%s",
        p,
        payload["graph"].number_of_nodes(),
        payload["graph"].number_of_edges(),
        payload.get("saved_at"),
    )
    return payload
