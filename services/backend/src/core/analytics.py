"""Аналитические функции, возвращающие чистые data-структуры (для API).

Все функции принимают (kz, G) и возвращают dict / list[dict].
Никаких print'ов — только данные.
"""

from __future__ import annotations

from typing import Any

import networkx as nx
import pandas as pd


# --------------------------------------------------------------------- helpers

def _node_meta(G: nx.DiGraph, v: str) -> dict[str, Any]:
    return {
        "tin": v,
        "name": G.nodes[v].get("volt_name"),
        "is_non_resident": G.nodes[v].get("is_non_resident"),
        "in_degree": G.in_degree(v),
        "out_degree": G.out_degree(v),
    }


def _node_role(G: nx.DiGraph, v: str) -> str:
    is_nr = G.nodes[v].get("is_non_resident")
    in_d = G.in_degree(v)
    out_d = G.out_degree(v)
    if is_nr:
        return "non_resident_importer"
    if in_d == 0:
        return "source"
    if out_d == 0:
        return "sink"
    return "intermediary"


def _node_sales(G: nx.DiGraph, v: str) -> float:
    return float(sum(w for _, _, w in G.out_edges(v, data="weight") if w))


def _node_purchases(G: nx.DiGraph, v: str) -> float:
    return float(sum(w for _, _, w in G.in_edges(v, data="weight") if w))


# ------------------------------------------------------------------ aggregate

def compute_aggregate(kz: dict, G: nx.DiGraph) -> dict[str, Any]:
    total_sales = 0.0
    total_import = 0.0
    n_with_sales = 0
    for v in G.nodes:
        if G.out_degree(v) == 0:
            continue
        s = _node_sales(G, v)
        if s <= 0:
            continue
        total_sales += s
        total_import += s * (1.0 - kz[v])
        n_with_sales += 1

    pct_import = (total_import / total_sales * 100.0) if total_sales > 0 else 0.0
    return {
        "sellers_count": n_with_sales,
        "total_sales": total_sales,
        "import_value": total_import,
        "domestic_value": total_sales - total_import,
        "import_share_pct": pct_import,
        "domestic_share_pct": 100.0 - pct_import,
    }


# --------------------------------------------------------------- distribution

def compute_distribution(kz: dict) -> dict[str, Any]:
    bins = [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99, 1.0001]
    labels = ["0.0–0.1", "0.1–0.3", "0.3–0.5", "0.5–0.7", "0.7–0.9", "0.9–0.99", "≈1.0"]
    series = pd.Series(kz)
    binned = pd.cut(series, bins=bins, labels=labels, include_lowest=True, right=False)
    counts = binned.value_counts().sort_index()
    total = int(counts.sum())
    histogram = [
        {"label": str(label), "count": int(cnt), "pct": (cnt / total * 100.0) if total else 0.0}
        for label, cnt in counts.items()
    ]
    desc = series.describe()
    return {
        "total": total,
        "histogram": histogram,
        "summary": {
            "mean": float(desc["mean"]),
            "std": float(desc["std"]),
            "min": float(desc["min"]),
            "p25": float(desc["25%"]),
            "p50": float(desc["50%"]),
            "p75": float(desc["75%"]),
            "max": float(desc["max"]),
        },
    }


# ---------------------------------------------------------------- top tables

def compute_top_importers(kz: dict, G: nx.DiGraph, n: int = 10) -> list[dict[str, Any]]:
    """Топ компаний по абсолютному импортному вкладу: sales × (1 − kz)."""
    rows = []
    for v in G.nodes:
        if G.out_degree(v) == 0:
            continue
        sales = _node_sales(G, v)
        kz_v = kz[v]
        import_value = sales * (1.0 - kz_v)
        if import_value < 1.0:
            continue
        rows.append({
            "tin": v,
            "name": G.nodes[v].get("volt_name"),
            "is_non_resident": bool(G.nodes[v].get("is_non_resident")),
            "kz": kz_v,
            "sales": sales,
            "import_value": import_value,
        })
    rows.sort(key=lambda r: r["import_value"], reverse=True)
    return rows[:n]


# ------------------------------------------------------------------ list cases

def compute_list_cases(kz: dict, G: nx.DiGraph, n: int = 5) -> dict[str, Any]:
    """Меню кандидатов по 4 архетипам."""

    importers: list[dict] = []
    for v in G.nodes:
        if not G.nodes[v].get("is_non_resident"):
            continue
        s = _node_sales(G, v)
        if s <= 0:
            continue
        importers.append({
            "tin": v,
            "name": G.nodes[v].get("volt_name"),
            "sales": s,
            "buyers_count": G.out_degree(v),
        })
    importers.sort(key=lambda r: r["sales"], reverse=True)

    dependents: list[dict] = []
    for v in G.nodes:
        if G.nodes[v].get("is_non_resident"):
            continue
        if G.in_degree(v) == 0:
            continue
        s = _node_sales(G, v)
        if s < 10_000_000 or kz[v] >= 0.7:
            continue
        dependents.append({
            "tin": v,
            "name": G.nodes[v].get("volt_name"),
            "sales": s,
            "kz": kz[v],
        })
    dependents.sort(key=lambda r: r["kz"])

    # Участники циклов (SCC размером > 1) не могут быть «чистыми отечественными»
    _cycle_nodes: set = set()
    for comp in nx.strongly_connected_components(G):
        if len(comp) > 1:
            _cycle_nodes.update(comp)

    clean: list[dict] = []
    for v in G.nodes:
        if G.nodes[v].get("is_non_resident"):
            continue
        if v in _cycle_nodes:
            continue
        s = _node_sales(G, v)
        if s < 100_000_000 or kz[v] < 0.99:
            continue
        clean.append({
            "tin": v,
            "name": G.nodes[v].get("volt_name"),
            "sales": s,
            "kz": kz[v],
        })
    clean.sort(key=lambda r: r["sales"], reverse=True)

    cycles: list[dict] = []
    for comp in nx.strongly_connected_components(G):
        if len(comp) <= 1:
            continue
        members = []
        for m in sorted(comp):
            members.append({
                "tin": m,
                "name": G.nodes[m].get("volt_name"),
                "kz": kz[m],
                "sales": _node_sales(G, m),
            })
        cycles.append({"size": len(comp), "members": members})
    cycles.sort(key=lambda c: c["size"], reverse=True)

    return {
        "importers": importers[:n],
        "dependents": dependents[:n],
        "clean": clean[:n],
        "cycles": cycles[:n],
    }


# --------------------------------------------------------- company profile

def _backward_view(kz: dict, G: nx.DiGraph, target: str, max_layers: int = 6) -> dict[str, Any]:
    in_deg = G.in_degree(target)
    if in_deg == 0:
        return {
            "applicable": False,
            "reason": (
                "Это нерезидент — у него нет поставщиков в нашем графе."
                if G.nodes[target].get("is_non_resident")
                else "Это узел-источник: в данных нет его поставщиков."
            ),
            "suppliers": [],
            "direct_import": None,
            "layers": [],
            "cone_size": 1,
        }

    purchases = _node_purchases(G, target)
    suppliers = []
    for u, _, w in G.in_edges(target, data="weight"):
        if not w:
            continue
        share = w / purchases if purchases else 0.0
        suppliers.append({
            "tin": u,
            "name": G.nodes[u].get("volt_name"),
            "is_non_resident": bool(G.nodes[u].get("is_non_resident")),
            "weight": float(w),
            "share": float(share),
            "kz": kz.get(u, 0.0),
        })
    suppliers.sort(key=lambda r: r["weight"], reverse=True)

    nr_total = sum(r["weight"] for r in suppliers if r["is_non_resident"])
    nr_count = sum(1 for r in suppliers if r["is_non_resident"])
    direct_import = {
        "value": float(nr_total),
        "share": (nr_total / purchases) if purchases else 0.0,
        "non_resident_suppliers_count": nr_count,
    }

    R = G.reverse(copy=False)
    visited = {target}
    layer = {target}
    layers = []
    for L in range(1, max_layers + 1):
        next_layer = set()
        for v in layer:
            for u in R.successors(v):
                if u not in visited:
                    next_layer.add(u)
                    visited.add(u)
        if not next_layer:
            break
        avg_kz = sum(kz.get(u, 0) for u in next_layer) / len(next_layer)
        nr_count_layer = sum(1 for u in next_layer if G.nodes[u].get("is_non_resident"))
        layers.append({
            "level": L,
            "size": len(next_layer),
            "avg_kz": float(avg_kz),
            "non_resident_count": int(nr_count_layer),
        })
        layer = next_layer

    return {
        "applicable": True,
        "suppliers": suppliers[:10],
        "suppliers_total": len(suppliers),
        "direct_import": direct_import,
        "layers": layers,
        "cone_size": len(visited),
        "cone_share": len(visited) / G.number_of_nodes(),
    }


def _forward_view(kz: dict, G: nx.DiGraph, target: str, max_layers: int = 5) -> dict[str, Any]:
    out_deg = G.out_degree(target)
    if out_deg == 0:
        return {
            "applicable": False,
            "reason": "У компании нет покупателей в графе — она конечный потребитель.",
            "customers": [],
            "layers": [],
            "cone_size": 1,
        }

    customers = []
    for _, c, w in G.out_edges(target, data="weight"):
        if not w:
            continue
        c_purchases = _node_purchases(G, c)
        share_in_buyer = (w / c_purchases) if c_purchases else 0.0
        customers.append({
            "tin": c,
            "name": G.nodes[c].get("volt_name"),
            "weight": float(w),
            "share_in_buyer": float(share_in_buyer),
            "kz": kz.get(c, 0.0),
        })
    customers.sort(key=lambda r: r["weight"], reverse=True)

    visited = {target}
    layer = {target}
    layers = []
    for L in range(1, max_layers + 1):
        next_layer = set()
        for v in layer:
            for u in G.successors(v):
                if u not in visited:
                    next_layer.add(u)
                    visited.add(u)
        if not next_layer:
            break
        layer_sales = 0.0
        n_end = 0
        for u in next_layer:
            layer_sales += _node_sales(G, u)
            if G.out_degree(u) == 0:
                n_end += 1
        avg_kz = sum(kz.get(u, 0) for u in next_layer) / len(next_layer)
        layers.append({
            "level": L,
            "size": len(next_layer),
            "layer_sales": float(layer_sales),
            "avg_kz": float(avg_kz),
            "end_consumers": int(n_end),
        })
        layer = next_layer

    return {
        "applicable": True,
        "customers": customers[:10],
        "customers_total": len(customers),
        "layers": layers,
        "cone_size": len(visited),
        "cone_share": len(visited) / G.number_of_nodes(),
    }


def compute_company_profile(kz: dict, G: nx.DiGraph, target: str) -> dict[str, Any] | None:
    """Полный профиль компании: карточка + backward + forward.

    Возвращает None, если узла нет в графе.
    """
    if target not in G:
        return None

    sales = _node_sales(G, target)
    kz_v = kz[target]
    card = {
        **_node_meta(G, target),
        "role": _node_role(G, target),
        "purchases": _node_purchases(G, target),
        "sales": sales,
        "kz": kz_v,
        "import_value_in_sales": sales * (1.0 - kz_v),
    }

    return {
        "card": card,
        "backward": _backward_view(kz, G, target),
        "forward": _forward_view(kz, G, target),
    }
