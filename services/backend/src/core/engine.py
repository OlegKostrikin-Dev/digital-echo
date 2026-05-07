"""Оркестратор: полный прогон расчёта индекса КС.

Основная функция `compute_state(days)` собирает граф, обогащает из VoltDB
и считает kz_content. Возвращает структуру, пригодную для повторного
использования в API (in-memory).

CLI-скрипт `kz_index.py` использует свою копию кода — он печатает в stdout.
Здесь же — чисто данные, без печати, чтобы потом отдать через FastAPI.
"""

from __future__ import annotations

import math
import os
from datetime import date, timedelta
from typing import Any, Optional

import networkx as nx
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

from .edges import (
    EDGES_QUERY,
    NODE_ATTRS_QUERY,
    build_connection_url,
    build_synthetic_connection_url,
)
from .synthetic_esf import FULL_SYNTHETIC_CATALOG
from .volt_resolver import TaxpayerResolver, _pad
from .voltdb_client import VoltDBClient, VoltDBConfigError


BIN_DTYPE = {"source": "string", "target": "string"}


def _resolve_load_edges_bounds(
    days: int,
    date_from: Optional[date],
    date_to: Optional[date],
) -> tuple[date, date, dict[str, Any]]:
    """Возвращает (date_from, date_to, extra_meta)."""
    extra: dict[str, Any] = {}
    if date_from is not None and date_to is not None:
        return date_from, date_to, {**extra, "period_mode": "explicit"}
    if os.getenv("MYSQL_USE_SYNTHETIC", "0").strip().lower() in ("1", "true", "yes"):
        # Как у генератора без --year: [сегодня − days … сегодня); days задаёт UI (/api/recompute).
        # Календарный год: ESF_SYNTHETIC_WINDOW=calendar и ESF_SYNTHETIC_YEAR.
        win = os.getenv("ESF_SYNTHETIC_WINDOW", "rolling").strip().lower()
        if win in ("calendar", "year", "calendar_year"):
            year = int(os.getenv("ESF_SYNTHETIC_YEAR", str(date.today().year)))
            d0 = date(year, 1, 1)
            d1 = date(year + 1, 1, 1)
            return d0, d1, {**extra, "period_mode": "synthetic_calendar_year", "synthetic_year": year}
        today = date.today()
        d0 = today - timedelta(days=days)
        d1 = today
        return d0, d1, {**extra, "period_mode": "synthetic_rolling", "days": days}
    today = date.today()
    return today - timedelta(days=days), today, {**extra, "period_mode": "rolling_days", "days": days}


def load_edges(
    days: int = 90,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    connection_url: Optional[str] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Возвращает (df_edges, meta).

    При ``MYSQL_USE_SYNTHETIC=1``: БД из ``MYSQL_SYNTHETIC_*``. Окно дат: по умолчанию
    скользящие ``days`` (как генератор без ``--year``); календарный год — если
    ``ESF_SYNTHETIC_WINDOW=calendar`` и ``ESF_SYNTHETIC_YEAR``.
    """
    load_dotenv(override=True)  # override=True — всегда подхватывать .env без рестарта
    if connection_url is not None:
        url = connection_url
    elif os.getenv("MYSQL_USE_SYNTHETIC", "0").strip().lower() in ("1", "true", "yes"):
        url = build_synthetic_connection_url()
    else:
        url = build_connection_url()

    d_from, d_to, period_meta = _resolve_load_edges_bounds(days, date_from, date_to)

    sa_engine = create_engine(url, pool_pre_ping=True)
    params = {"date_from": d_from, "date_to": d_to}
    with sa_engine.connect() as conn:
        df_edges = pd.read_sql(EDGES_QUERY, conn, params=params, dtype=BIN_DTYPE)

    meta: dict[str, Any] = {
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "raw_edges": int(len(df_edges)),
        **period_meta,
    }
    if period_meta.get("period_mode") == "rolling_days":
        meta["days"] = days
    elif period_meta.get("period_mode") == "synthetic_rolling":
        meta["days"] = days
    elif period_meta.get("period_mode") == "synthetic_calendar_year":
        meta["days"] = (d_to - d_from).days
    return df_edges, meta


def build_graph(df_edges: pd.DataFrame) -> tuple[nx.DiGraph, dict[str, Any]]:
    valid = df_edges[df_edges["weight"] > 0].copy()
    G = nx.from_pandas_edgelist(
        valid,
        source="source", target="target",
        edge_attr=["weight", "invoice_count"],
        create_using=nx.DiGraph,
    )
    return G, {
        "edges_after_filter": int(len(valid)),
        "edges_dropped": int(len(df_edges) - len(valid)),
        "nodes": int(G.number_of_nodes()),
    }


def _voltdb_unavailable_meta(G: nx.DiGraph, error: str) -> dict[str, Any]:
    for v in G.nodes:
        G.nodes[v]["is_non_resident"] = None
        G.nodes[v]["volt_name"] = None
    return {
        "voltdb_available": False,
        "error": error,
        "resolved": 0,
        "non_resident": 0,
        "missing": int(G.number_of_nodes()),
        "unknown_state": 0,
    }


def enrich_with_voltdb(G: nx.DiGraph) -> dict[str, Any]:
    """Достаёт резидентность всех узлов графа из VoltDB.taxpayer.

    Записывает в G.nodes[v] атрибуты `is_non_resident` и `volt_name`.
    Если VoltDB недоступен — все узлы помечаются как unknown (резиденты).
    """
    try:
        volt = VoltDBClient.from_env()
    except VoltDBConfigError as exc:
        return _voltdb_unavailable_meta(G, str(exc))

    nodes = list(G.nodes)
    try:
        with volt:
            resolver = TaxpayerResolver(volt)
            info = resolver.lookup_batch(nodes)
    except Exception as exc:  # connect / AdHoc / сеть — пересчёт не падает
        return _voltdb_unavailable_meta(G, f"{type(exc).__name__}: {exc}")

    n_resolved = 0
    n_non_resident = 0
    n_missing = 0
    n_unknown_state = 0

    for v in G.nodes:
        rec = info.get(_pad(v))
        if rec is None:
            G.nodes[v]["is_non_resident"] = None
            G.nodes[v]["volt_name"] = None
            n_missing += 1
        else:
            res = rec.get("resident")
            if res == 0:
                G.nodes[v]["is_non_resident"] = True
                n_non_resident += 1
            elif res == 1:
                G.nodes[v]["is_non_resident"] = False
            else:
                G.nodes[v]["is_non_resident"] = None
                n_unknown_state += 1
            G.nodes[v]["volt_name"] = rec.get("name")
            n_resolved += 1

    return {
        "voltdb_available": True,
        "resolved": n_resolved,
        "non_resident": n_non_resident,
        "missing": n_missing,
        "unknown_state": n_unknown_state,
    }


def _norm_tin_key(t: Any) -> str:
    """Ключ БИН для сопоставления узлов графа с MySQL и каталогом синтетики."""
    if t is None:
        return ""
    if hasattr(t, "item"):
        try:
            t = t.item()
        except Exception:
            pass
    if isinstance(t, bool):
        return str(t)
    if isinstance(t, int):
        return str(t)
    if isinstance(t, float) and math.isfinite(t) and t == math.trunc(t):
        return str(int(t))
    s = str(t).strip()
    if not s or s.lower() == "nan":
        return ""
    if s.isdigit():
        return str(int(s))
    try:
        x = float(s)
        if math.isfinite(x) and x == math.trunc(x):
            return str(int(x))
    except ValueError:
        pass
    return s


def apply_synthetic_mysql_seller_nr_flags(
    G: nx.DiGraph,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    """Перекрывает атрибуты узлов в демо-режиме: NR из ЭСФ (шапка), имена из каталога.

    Флаги продавца берутся из MySQL (если есть строки за период); для БИН из
    ``FULL_SYNTHETIC_CATALOG`` имя узла всегда из каталога, чтобы VoltDB не
    вносил расхождений между разделами UI.
    """
    load_dotenv(override=True)
    flag = os.getenv("MYSQL_USE_SYNTHETIC", "0").strip().lower()
    if flag not in ("1", "true", "yes"):
        return {"mysql_nr_overlay": False}

    url = build_synthetic_connection_url()
    sa_engine = create_engine(url, pool_pre_ping=True)
    with sa_engine.connect() as conn:
        df = pd.read_sql(
            NODE_ATTRS_QUERY,
            conn,
            params={"date_from": date_from, "date_to": date_to},
            dtype={"tin": "string"},
        )
    rev = {_norm_tin_key(n): n for n in G.nodes}

    matched = 0
    if not df.empty:
        for _, row in df.iterrows():
            tkey = _norm_tin_key(row["tin"])
            if tkey not in rev:
                continue
            v = rev[tkey]
            fl = int(row["is_non_resident"] or 0)
            G.nodes[v]["is_non_resident"] = bool(fl)
            matched += 1

    # БИН из каталога: имя всегда берём из каталога (перебивает VoltDB).
    # Иначе один и тот же узел после VoltDB может отображаться как Samsung в ①
    # и как чужое казахстанское название в ③ из‑за рассинхрона справочника.
    name_matched = 0
    for tin_int, info in FULL_SYNTHETIC_CATALOG.items():
        tkey = _norm_tin_key(tin_int)
        if tkey not in rev:
            continue
        v = rev[tkey]
        G.nodes[v]["volt_name"] = info["name"]
        name_matched += 1
        if G.nodes[v].get("is_non_resident") is None:
            G.nodes[v]["is_non_resident"] = bool(info["is_nr"])

    return {
        "mysql_nr_overlay": True,
        "mysql_nr_source_rows": int(len(df)),
        "mysql_nr_matched_nodes": matched,
        "name_overlay_matched": name_matched,
    }


def compute_kz_content(
    G: nx.DiGraph,
    max_iter: int = 500,
    tol: float = 1e-7,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Возвращает (kz_dict, meta). Алгоритм fixed-point итераций.

    Идентичен `kz_index.compute_kz_content`, но без print'ов и со стат-выходом.
    """
    fixed: set = set()
    kz: dict[str, float] = {}

    for v in G.nodes:
        is_nr = G.nodes[v].get("is_non_resident")
        if is_nr is True:
            kz[v] = 0.0
            fixed.add(v)
        elif G.in_degree(v) == 0:
            kz[v] = 1.0
            fixed.add(v)
        else:
            kz[v] = 1.0

    n_fixed_nr = sum(1 for v in fixed if G.nodes[v].get("is_non_resident") is True)
    n_fixed_src = len(fixed) - n_fixed_nr

    in_edges = {v: list(G.in_edges(v, data="weight")) for v in G.nodes if v not in fixed}

    iterations = 0
    converged = False
    delta_max_final = 0.0
    for it in range(1, max_iter + 1):
        delta_max = 0.0
        new_kz = kz.copy()
        for v, ies in in_edges.items():
            total_w = 0.0
            acc = 0.0
            for u, _, w in ies:
                if w is None or w <= 0:
                    continue
                total_w += w
                acc += w * kz[u]
            if total_w > 0:
                val = acc / total_w
                d = abs(val - kz[v])
                if d > delta_max:
                    delta_max = d
                new_kz[v] = val
        kz = new_kz
        iterations = it
        delta_max_final = delta_max
        if delta_max < tol:
            converged = True
            break

    return kz, {
        "fixed_total": len(fixed),
        "fixed_non_resident": n_fixed_nr,
        "fixed_resident_source": n_fixed_src,
        "free_nodes": int(G.number_of_nodes() - len(fixed)),
        "iterations": iterations,
        "converged": converged,
        "delta_max": delta_max_final,
        "tol": tol,
    }


def compute_state(
    days: int = 90,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> dict[str, Any]:
    """Полный прогон. Возвращает dict с graph, kz и метаданными.

    Это «тяжёлая» операция (~80 сек на 90 дней / 100K узлов).
    Результат пригоден для in-memory кэширования.
    """
    df_edges, edges_meta = load_edges(days=days, date_from=date_from, date_to=date_to)
    if df_edges.empty:
        return {
            "graph": nx.DiGraph(),
            "kz": {},
            "meta": {
                **edges_meta,
                "empty": True,
            },
        }

    G, graph_meta = build_graph(df_edges)
    voltdb_meta = enrich_with_voltdb(G)
    d0 = date.fromisoformat(edges_meta["date_from"])
    d1 = date.fromisoformat(edges_meta["date_to"])
    mysql_nr_meta = apply_synthetic_mysql_seller_nr_flags(G, d0, d1)
    kz, compute_meta = compute_kz_content(G)

    return {
        "graph": G,
        "kz": kz,
        "meta": {
            **edges_meta,
            **graph_meta,
            "voltdb": voltdb_meta,
            "mysql_nr": mysql_nr_meta,
            "compute": compute_meta,
        },
    }
