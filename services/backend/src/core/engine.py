"""Оркестратор: полный прогон расчёта индекса КС.

Основная функция `compute_state(days)` собирает граф, обогащает из VoltDB
и считает kz_content. Возвращает структуру, пригодную для повторного
использования в API (in-memory).

CLI-скрипт `kz_index.py` использует свою копию кода — он печатает в stdout.
Здесь же — чисто данные, без печати, чтобы потом отдать через FastAPI.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import networkx as nx
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

from .edges import EDGES_QUERY, build_connection_url
from .volt_resolver import TaxpayerResolver, _pad
from .voltdb_client import VoltDBClient, VoltDBConfigError


BIN_DTYPE = {"source": "string", "target": "string"}


def load_edges(days: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Возвращает (df_edges, meta).

    `meta` содержит date_from, date_to, days и сырые счётчики.
    """
    load_dotenv()
    url = build_connection_url()

    today = date.today()
    date_from = today - timedelta(days=days)
    date_to = today

    sa_engine = create_engine(url, pool_pre_ping=True)
    params = {"date_from": date_from, "date_to": date_to}
    with sa_engine.connect() as conn:
        df_edges = pd.read_sql(EDGES_QUERY, conn, params=params, dtype=BIN_DTYPE)

    return df_edges, {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "days": days,
        "raw_edges": int(len(df_edges)),
    }


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


def enrich_with_voltdb(G: nx.DiGraph) -> dict[str, Any]:
    """Достаёт резидентность всех узлов графа из VoltDB.taxpayer.

    Записывает в G.nodes[v] атрибуты `is_non_resident` и `volt_name`.
    Если VoltDB недоступен — все узлы помечаются как unknown (резиденты).
    """
    try:
        volt = VoltDBClient.from_env()
    except VoltDBConfigError as exc:
        for v in G.nodes:
            G.nodes[v]["is_non_resident"] = None
            G.nodes[v]["volt_name"] = None
        return {
            "voltdb_available": False,
            "error": str(exc),
            "resolved": 0,
            "non_resident": 0,
            "missing": int(G.number_of_nodes()),
            "unknown_state": 0,
        }

    nodes = list(G.nodes)
    with volt:
        resolver = TaxpayerResolver(volt)
        info = resolver.lookup_batch(nodes)

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


def compute_state(days: int = 90) -> dict[str, Any]:
    """Полный прогон. Возвращает dict с graph, kz и метаданными.

    Это «тяжёлая» операция (~80 сек на 90 дней / 100K узлов).
    Результат пригоден для in-memory кэширования.
    """
    df_edges, edges_meta = load_edges(days=days)
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
    kz, compute_meta = compute_kz_content(G)

    return {
        "graph": G,
        "kz": kz,
        "meta": {
            **edges_meta,
            **graph_meta,
            "voltdb": voltdb_meta,
            "compute": compute_meta,
        },
    }
