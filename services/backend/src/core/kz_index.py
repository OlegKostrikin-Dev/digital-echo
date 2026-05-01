"""digital-echo-core: прототип расчёта индекса казахстанского содержания (КС).

Источники данных:
  - MySQL (ЭСФ-документы): взвешенный B2B-граф транзакций
  - VoltDB (taxpayer):     признак резидентности по БИН/ИИН

Алгоритм:
  1. Строим взвешенный направленный граф B2B-транзакций
     (ребро seller -> customer, вес = SUM(total_price_without_tax)).
  2. Через VoltDB.taxpayer определяем для каждого узла резидент/нерезидент.
  3. Для каждого узла-источника (нет входящих рёбер) задаём kz_content:
       1.0 если резидент, 0.0 если нерезидент.
  4. Для остальных узлов считаем kz_content итеративно:
       kz[v] = sum_{u : u->v} weight(u,v) * kz[u]  /  sum_{u : u->v} weight(u,v)
     То есть индекс компании = средневзвешенный индекс её поставщиков,
     где веса — суммы транзакций.
  5. Циклы обрабатываются автоматически через fixed-point итерации
     (как в алгоритме PageRank).

Допущения прототипа:
  - Нерезидент трактуется как 100% импорт (флаг RESIDENT=0 -> kz=0.0).
  - Возвраты и нулевые суммы фильтруются (weight <= 0 отсекаются).
  - Узлы, которых нет в TAXPAYER, считаются резидентами (оптимистично).
  - В будущем нужны справочники "производитель / посредник / физлицо"
    из вне ЭСФ для более точной классификации источников.
"""

import argparse
import sys
from datetime import date, timedelta

import networkx as nx
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from .edges import EDGES_QUERY, build_connection_url
from .volt_resolver import TaxpayerResolver
from .voltdb_client import VoltDBClient, VoltDBConfigError


BIN_DTYPE = {"source": "string", "target": "string"}


def fmt(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ")


def fmt_money(x: float) -> str:
    """Человеко-читаемые деньги: 12.5 млн ₸ / 1.34 млрд ₸."""
    if x is None:
        return "—"
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a >= 1e9:
        return f"{sign}{a/1e9:,.2f} млрд ₸".replace(",", " ")
    if a >= 1e6:
        return f"{sign}{a/1e6:,.2f} млн ₸".replace(",", " ")
    if a >= 1e3:
        return f"{sign}{a/1e3:,.0f} тыс ₸".replace(",", " ")
    return f"{sign}{a:,.0f} ₸".replace(",", " ")


def short_name(name: str | None, width: int = 35) -> str:
    if not name:
        return "(без имени)"
    return (name[: width - 1] + "…") if len(name) > width else name


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def subsection(title: str) -> None:
    print(f"\n— {title} —")


# ---------------------------------------------------------------------------
# Загрузка данных
# ---------------------------------------------------------------------------

def load_edges(days: int) -> pd.DataFrame:
    """Грузим только рёбра из MySQL — резидентность придёт из VoltDB."""
    load_dotenv()
    url = build_connection_url()

    today = date.today()
    date_from = today - timedelta(days=days)
    date_to = today
    print(f"[INFO] Период: {date_from} -> {date_to} ({days} дней)")

    engine = create_engine(url, pool_pre_ping=True)
    params = {"date_from": date_from, "date_to": date_to}

    with engine.connect() as conn:
        df_edges = pd.read_sql(EDGES_QUERY, conn, params=params, dtype=BIN_DTYPE)

    print(f"[INFO] Рёбер из MySQL: {len(df_edges):,}")
    return df_edges


# ---------------------------------------------------------------------------
# Построение графа + обогащение из VoltDB
# ---------------------------------------------------------------------------

def build_graph(df_edges: pd.DataFrame) -> nx.DiGraph:
    # Отсекаем шумовые рёбра: возвраты и нули
    valid = df_edges[df_edges["weight"] > 0].copy()
    print(f"[INFO] Рёбер после фильтра weight>0: {len(valid):,} "
          f"(отброшено {len(df_edges)-len(valid)})")

    G = nx.from_pandas_edgelist(
        valid,
        source="source", target="target",
        edge_attr=["weight", "invoice_count"],
        create_using=nx.DiGraph,
    )
    print(f"[INFO] Узлов в графе: {G.number_of_nodes():,}")
    return G


def enrich_with_voltdb(G: nx.DiGraph) -> dict[str, dict]:
    """Достаём резидентность всех узлов графа из VoltDB.taxpayer.

    Записываем G.nodes[v]['is_non_resident'] и G.nodes[v]['volt_name'].
    Возвращает агрегированную статистику.
    """
    section("ОБОГАЩЕНИЕ УЗЛОВ ИЗ VoltDB.taxpayer")

    try:
        volt = VoltDBClient.from_env()
    except VoltDBConfigError as exc:
        print(f"[WARN] VoltDB не сконфигурирован: {exc}")
        print("       Расчёт пойдёт без признаков резидентности — все узлы=резиденты.")
        for v in G.nodes:
            G.nodes[v]["is_non_resident"] = None
            G.nodes[v]["volt_name"] = None
        return {"resolved": 0, "non_resident": 0, "missing": G.number_of_nodes()}

    nodes = list(G.nodes)
    print(f"[INFO] Запрос резидентности для {len(nodes):,} BIN'ов...")

    with volt:
        resolver = TaxpayerResolver(volt)
        info = resolver.lookup_batch(nodes)

    # Считаем результаты
    n_resolved = 0
    n_non_resident = 0
    n_missing = 0
    n_unknown_state = 0

    for v in G.nodes:
        # ключ в info — 12-символьный padded; в графе — оригинальный (без нулей)
        from .volt_resolver import _pad
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
                # NULL или экзотика (например, RESIDENT=3)
                G.nodes[v]["is_non_resident"] = None
                n_unknown_state += 1
            G.nodes[v]["volt_name"] = rec.get("name")
            n_resolved += 1

    print(f"[INFO] Найдено в TAXPAYER: {n_resolved:,}")
    print(f"[INFO]   из них нерезидентов:        {n_non_resident:,}")
    print(f"[INFO]   из них с неизвестным RESIDENT: {n_unknown_state:,}")
    print(f"[INFO] НЕ найдено в TAXPAYER:        {n_missing:,}")

    return {
        "resolved": n_resolved,
        "non_resident": n_non_resident,
        "missing": n_missing,
        "unknown_state": n_unknown_state,
    }


# ---------------------------------------------------------------------------
# Итеративный расчёт индекса
# ---------------------------------------------------------------------------

def compute_kz_content(
    G: nx.DiGraph,
    max_iter: int = 500,
    tol: float = 1e-7,
) -> dict:
    """Возвращает dict {node: kz_content в [0,1]}.

    Ключевые правила:
      - Узел, помеченный как НЕРЕЗИДЕНТ, всегда имеет kz=0 (фиксируется,
        не пересчитывается). Логически: его продукция всегда импорт.
      - Резиденты-источники (in_degree=0): kz=1.0.
      - Остальные узлы — итеративно по средневзвешенному поставщиков.
    """

    # 1. Определяем фиксированные узлы (нерезиденты)
    fixed: set = set()
    kz: dict = {}

    for v in G.nodes:
        is_nr = G.nodes[v].get("is_non_resident")
        if is_nr is True:
            kz[v] = 0.0
            fixed.add(v)
        elif G.in_degree(v) == 0:
            # Резидент-источник или неизвестный — оптимистично 1.0
            kz[v] = 1.0
            fixed.add(v)
        else:
            kz[v] = 1.0  # стартовое значение для итераций

    n_fixed_nr = sum(1 for v in fixed if G.nodes[v].get("is_non_resident") is True)
    n_fixed_src = len(fixed) - n_fixed_nr
    print(f"[INFO] Зафиксировано узлов: {len(fixed):,}")
    print(f"[INFO]   нерезидентов (kz=0): {n_fixed_nr:,}")
    print(f"[INFO]   резидентов-источников (kz=1): {n_fixed_src:,}")
    print(f"[INFO] Свободных узлов для итераций: {G.number_of_nodes() - len(fixed):,}")

    # Кэш входящих рёбер для скорости
    in_edges = {v: list(G.in_edges(v, data="weight")) for v in G.nodes if v not in fixed}

    # Итерации — пересчитываем только свободные узлы
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
        if delta_max < tol:
            print(f"[OK] Сошлось за {it} итераций (delta={delta_max:.2e})")
            break
    else:
        print(f"[WARN] Не сошлось за {max_iter} итераций (delta={delta_max:.2e}). "
              "Возможны крупные циклы или числовая нестабильность.")

    return kz


# ---------------------------------------------------------------------------
# Аналитика
# ---------------------------------------------------------------------------

def show_distribution(kz: dict, G: nx.DiGraph) -> None:
    series = pd.Series(kz, name="kz_content")
    section("РАСПРЕДЕЛЕНИЕ ИНДЕКСА КС ПО ВСЕМ УЗЛАМ")
    print(series.describe().apply(lambda x: f"{x:.4f}").to_string())
    print()
    bins = [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99, 1.0001]
    labels = ["0.0–0.1", "0.1–0.3", "0.3–0.5", "0.5–0.7", "0.7–0.9", "0.9–0.99", "≈1.0"]
    binned = pd.cut(series, bins=bins, labels=labels, include_lowest=True, right=False)
    counts = binned.value_counts().sort_index()
    total = counts.sum()
    print("Гистограмма kz_content:")
    for label, cnt in counts.items():
        bar = "#" * int(50 * cnt / total) if total else ""
        print(f"  {str(label):>10} : {cnt:>7,} {bar}")


def show_top_import_dependent(kz: dict, G: nx.DiGraph, top_n: int = 10) -> None:
    section(f"ТОП-{top_n} КОМПАНИЙ ПО АБСОЛЮТНОМУ ИМПОРТНОМУ ВКЛАДУ")
    print("(сортировка по: продажи × (1 − kz) — сколько импорта впрыскивается в рынок)\n")

    rows = []
    for v in G.nodes:
        out_deg = G.out_degree(v)
        if out_deg == 0:
            continue
        sales = sum(w for _, _, w in G.out_edges(v, data="weight") if w)
        kz_v = kz[v]
        import_value = sales * (1.0 - kz_v)
        if import_value < 1.0:
            continue
        rows.append({
            "tin": v,
            "name": short_name(G.nodes[v].get("volt_name")),
            "kind": "нерезидент" if G.nodes[v].get("is_non_resident") else "",
            "kz": kz_v,
            "import_value": import_value,
            "sales": sales,
        })

    if not rows:
        print("Узлов с импортной составляющей не найдено.")
        return

    df = pd.DataFrame(rows).sort_values("import_value", ascending=False).head(top_n)
    print(f"{'BIN':>13}  {'Название':<37}  {'kz':>5}  "
          f"{'Импорт':>17}  {'Продажи':>17}  Вид")
    print("-" * 110)
    for _, r in df.iterrows():
        print(f"{r['tin']:>13}  {r['name']:<37}  {r['kz']:>5.2f}  "
              f"{fmt_money(r['import_value']):>17}  {fmt_money(r['sales']):>17}  {r['kind']}")


def show_aggregate_economy(kz: dict, G: nx.DiGraph) -> None:
    """Сколько процентов всего оборота за период имеет импортную составляющую."""
    section("АГРЕГАТ ПО ЭКОНОМИКЕ ЗА ПЕРИОД")
    total_sales = 0.0
    total_import = 0.0
    n_with_sales = 0
    for v in G.nodes:
        if G.out_degree(v) == 0:
            continue
        s = sum(w for _, _, w in G.out_edges(v, data="weight") if w)
        if s <= 0:
            continue
        total_sales += s
        total_import += s * (1.0 - kz[v])
        n_with_sales += 1

    pct = (total_import / total_sales * 100.0) if total_sales > 0 else 0.0
    print(f"  Компаний-продавцов:       {n_with_sales:,}")
    print(f"  Совокупный оборот:        {fmt_money(total_sales)}")
    print(f"  Импортная составляющая:   {fmt_money(total_import)}  ({pct:.2f}%)")
    print(f"  Казахстанская составляющая: {fmt_money(total_sales - total_import)}  ({100-pct:.2f}%)")


def _print_target_card(kz: dict, G: nx.DiGraph, target: str) -> dict:
    """Печатает «карточку» компании. Возвращает словарь с базовыми метриками."""
    in_deg = G.in_degree(target)
    out_deg = G.out_degree(target)
    is_nr = G.nodes[target].get("is_non_resident")
    name = G.nodes[target].get("volt_name") or "(без имени)"
    purchases = sum(w for _, _, w in G.in_edges(target, data="weight") if w)
    sales = sum(w for _, _, w in G.out_edges(target, data="weight") if w)

    role = ("нерезидент-импортёр" if is_nr
            else "источник (нет поставщиков в графе)" if in_deg == 0
            else "конечный потребитель" if out_deg == 0
            else "посредник")

    print(f"  Компания:    {name}")
    print(f"  BIN:         {target}")
    print(f"  Роль:        {role}")
    print(f"  Закупки:     {fmt_money(purchases):<20} ({in_deg} поставщиков)")
    print(f"  Продажи:     {fmt_money(sales):<20} ({out_deg} покупателей)")
    print(f"  ▶ ИНДЕКС КС: {kz[target]*100:.2f}%  (kz = {kz[target]:.4f})")
    if sales > 0:
        import_value = sales * (1.0 - kz[target])
        print(f"  ▶ Импортная составляющая в продажах: {fmt_money(import_value)}")
    return {
        "in_deg": in_deg, "out_deg": out_deg, "is_nr": is_nr,
        "purchases": purchases, "sales": sales,
    }


def show_backward_view(kz: dict, G: nx.DiGraph, target: str, max_layers: int = 6) -> None:
    """Анализ ВВЕРХ по графу: откуда у компании импорт. Полезно для посредников."""
    info = G.nodes[target]
    in_deg = G.in_degree(target)
    if in_deg == 0:
        subsection("Откуда поступает товар (backward-конус)")
        if info.get("is_non_resident"):
            print("  Это нерезидент — у него нет поставщиков в нашем графе.")
            print("  Весь его исходящий поток считается импортом по определению.")
        else:
            print("  Это узел-источник: в данных нет его поставщиков.")
            print("  Возможные причины: производитель / физлицо / выписки за пределами периода.")
        return

    purchases = sum(w for _, _, w in G.in_edges(target, data="weight") if w)
    subsection("Откуда поступает товар (backward-конус)")

    # 1. Прямые поставщики
    suppliers = []
    for u, _, w in G.in_edges(target, data="weight"):
        if not w:
            continue
        share = w / purchases if purchases else 0
        suppliers.append((u, w, share, kz.get(u, 0.0)))
    suppliers.sort(key=lambda x: -x[1])

    print(f"\n  Прямых поставщиков: {len(suppliers)}. Топ-10 по сумме:")
    print(f"  {'BIN':>13}  {'Название':<35}  {'Сумма':>15}  {'Доля':>7}  {'kz':>5}  Вид")
    print("  " + "-" * 100)
    for u, w, share, kz_u in suppliers[:10]:
        nm = short_name(G.nodes[u].get("volt_name"))
        kind = "нерезидент" if G.nodes[u].get("is_non_resident") else ""
        print(f"  {u:>13}  {nm:<35}  {fmt_money(w):>15}  "
              f"{share*100:>6.1f}%  {kz_u:>5.2f}  {kind}")
    print("  (Доля = доля поставщика в общих закупках компании)")

    # 2. Прямые нерезиденты-поставщики (если есть) — ключевой инсайт для бизнеса
    nr_suppliers = [(u, w, share) for u, w, share, _ in suppliers
                    if G.nodes[u].get("is_non_resident")]
    if nr_suppliers:
        nr_total = sum(w for _, w, _ in nr_suppliers)
        nr_share = nr_total / purchases if purchases else 0
        print(f"\n  ⚠ Прямой импорт от нерезидентов: {fmt_money(nr_total)} "
              f"({nr_share*100:.1f}% всех закупок) от {len(nr_suppliers)} нерезидентов.")
    else:
        # Импорт пришёл «через посредников». Найдём среди топ-поставщиков с низким kz.
        tainted = [(u, w, share, kz_u) for u, w, share, kz_u in suppliers if kz_u < 0.7]
        if tainted:
            print(f"\n  ⚠ Прямых нерезидентов нет, но импорт «приходит через посредников»:")
            for u, w, share, kz_u in tainted[:3]:
                nm = short_name(G.nodes[u].get("volt_name"))
                print(f"    └─ {u} {nm}  kz={kz_u:.2f}  закупка: {fmt_money(w)} ({share*100:.1f}%)")

    # 3. BFS по слоям
    print(f"\n  Распространение по слоям вверх (макс {max_layers}):")
    R = G.reverse(copy=False)
    visited = {target}
    layer = {target}
    for L in range(1, max_layers + 1):
        next_layer = set()
        for v in layer:
            for u in R.successors(v):
                if u not in visited:
                    next_layer.add(u)
                    visited.add(u)
        if not next_layer:
            print(f"    Слой {L}: пусто (цепочка закончилась)")
            break
        avg_kz = sum(kz.get(u, 0) for u in next_layer) / len(next_layer)
        nr_count = sum(1 for u in next_layer if G.nodes[u].get("is_non_resident"))
        print(f"    Слой {L}: {len(next_layer):>5} компаний  "
              f"avg kz={avg_kz:.3f}  нерезидентов: {nr_count}")
        layer = next_layer
    print(f"    Всего в backward-конусе: {len(visited)} компаний "
          f"({len(visited)/G.number_of_nodes()*100:.2f}% графа)")


def show_forward_view(kz: dict, G: nx.DiGraph, target: str, max_layers: int = 5) -> None:
    """Анализ ВНИЗ по графу: куда расходится продукция этой компании.

    Особенно ценно для нерезидентов: показывает, как далеко проникает импорт.
    """
    out_deg = G.out_degree(target)
    if out_deg == 0:
        subsection("Куда уходит товар (forward-конус)")
        print("  У компании нет покупателей в графе — она конечный потребитель в этом периоде.")
        return

    sales = sum(w for _, _, w in G.out_edges(target, data="weight") if w)
    subsection("Куда уходит товар (forward-конус)")

    # 1. Прямые покупатели — топ
    customers = []
    for _, c, w in G.out_edges(target, data="weight"):
        if not w:
            continue
        c_purchases = sum(ww for _, _, ww in G.in_edges(c, data="weight") if ww)
        share_in_buyer = (w / c_purchases) if c_purchases else 0
        customers.append((c, w, share_in_buyer, kz.get(c, 0.0)))
    customers.sort(key=lambda x: -x[1])

    print(f"\n  Прямых покупателей: {len(customers)}. Топ-10 по объёму:")
    print(f"  {'BIN':>13}  {'Название':<35}  {'Закупил':>15}  "
          f"{'Доля':>7}  {'kz':>5}")
    print("  " + "-" * 100)
    for c, w, share_in_buyer, kz_c in customers[:10]:
        nm = short_name(G.nodes[c].get("volt_name"))
        print(f"  {c:>13}  {nm:<35}  {fmt_money(w):>15}  "
              f"{share_in_buyer*100:>6.1f}%  {kz_c:>5.2f}")
    print("  (Доля = доля этой закупки в общих закупках покупателя)")

    # 2. BFS вниз
    print(f"\n  Распространение по слоям вниз (макс {max_layers}):")
    visited = {target}
    layer = {target}
    for L in range(1, max_layers + 1):
        next_layer = set()
        for v in layer:
            for u in G.successors(v):
                if u not in visited:
                    next_layer.add(u)
                    visited.add(u)
        if not next_layer:
            print(f"    Слой {L}: пусто (товар «остановился» на слое {L-1})")
            break
        layer_sales = 0.0
        n_end = 0
        for u in next_layer:
            s = sum(w for _, _, w in G.out_edges(u, data="weight") if w)
            layer_sales += s
            if G.out_degree(u) == 0:
                n_end += 1
        avg_kz = sum(kz.get(u, 0) for u in next_layer) / len(next_layer)
        end_note = f" (из них конечных потребителей: {n_end})" if n_end else ""
        print(f"    Слой {L}: {len(next_layer):>5} компаний  "
              f"их продажи всего: {fmt_money(layer_sales):<18}  "
              f"avg kz={avg_kz:.3f}{end_note}")
        layer = next_layer
    print(f"    Всего в forward-конусе: {len(visited)} компаний "
          f"({len(visited)/G.number_of_nodes()*100:.2f}% графа)")


def analyze_target(kz: dict, G: nx.DiGraph, target: str) -> None:
    """Универсальный профиль: карточка + backward + forward."""
    section(f"ПРОФИЛЬ КОМПАНИИ: BIN = {target}")
    if target not in G:
        print(f"[ERROR] Узел {target} отсутствует в графе.")
        return
    _print_target_card(kz, G, target)
    show_backward_view(kz, G, target)
    show_forward_view(kz, G, target)


def auto_pick_target(kz: dict, G: nx.DiGraph) -> str | None:
    """Подбираем посредника с большими продажами и нетривиальным kz_content."""
    candidates = []
    for v in G.nodes:
        if G.in_degree(v) == 0 or G.out_degree(v) == 0:
            continue
        sales = sum(w for _, _, w in G.out_edges(v, data="weight") if w)
        if sales < 10_000_000:
            continue
        candidates.append((v, sales, kz[v]))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[2], -x[1]))
    return candidates[0][0]


def list_cases(kz: dict, G: nx.DiGraph, n: int = 5) -> None:
    """Меню рекомендованных BIN'ов по архетипам — для подготовки демо."""
    section("МЕНЮ КАНДИДАТОВ ДЛЯ ДЕМО (по архетипам)")
    print("Используй BIN из любой группы как аргумент --targets.\n")

    def _print_row(tin: str, name: str, sales: float, kz_v: float, extra: str = "") -> None:
        print(f"  {tin:>13}  {short_name(name):<37}  "
              f"{fmt_money(sales):>15}  kz={kz_v:>5.2f}  {extra}")

    # 1. Импортёры (нерезиденты с реальными продажами)
    print("[1] ИМПОРТЁРЫ — нерезиденты с реальными продажами:")
    nr = []
    for v in G.nodes:
        if not G.nodes[v].get("is_non_resident"):
            continue
        s = sum(w for _, _, w in G.out_edges(v, data="weight") if w)
        if s <= 0:
            continue
        nr.append((v, G.nodes[v].get("volt_name") or "", s, G.out_degree(v)))
    nr.sort(key=lambda x: -x[2])
    if not nr:
        print("    (нет в этом периоде)")
    for tin, name, s, n_buyers in nr[:n]:
        _print_row(tin, name, s, 0.0, f"{n_buyers} покупателей")

    # 2. Зависимые от импорта (резиденты с kz < 0.7 и заметными продажами)
    print("\n[2] ЗАВИСИМЫЕ ОТ ИМПОРТА — резиденты с kz < 0.7 и продажами > 10 млн:")
    deps = []
    for v in G.nodes:
        if G.nodes[v].get("is_non_resident"):
            continue
        if G.in_degree(v) == 0:
            continue
        s = sum(w for _, _, w in G.out_edges(v, data="weight") if w)
        if s < 10_000_000:
            continue
        if kz[v] >= 0.7:
            continue
        deps.append((v, G.nodes[v].get("volt_name") or "", s, kz[v]))
    deps.sort(key=lambda x: x[3])
    if not deps:
        print("    (нет таких — все цепочки либо чистые, либо очень короткие)")
    for tin, name, s, k in deps[:n]:
        _print_row(tin, name, s, k)

    # 3. Чистые крупные (kz≈1, продажи > 100 млн)
    print("\n[3] ЧИСТЫЕ КРУПНЫЕ — резиденты с kz ≈ 1.0 и продажами > 100 млн:")
    clean = []
    for v in G.nodes:
        if G.nodes[v].get("is_non_resident"):
            continue
        s = sum(w for _, _, w in G.out_edges(v, data="weight") if w)
        if s < 100_000_000:
            continue
        if kz[v] < 0.99:
            continue
        clean.append((v, G.nodes[v].get("volt_name") or "", s, kz[v]))
    clean.sort(key=lambda x: -x[2])
    if not clean:
        print("    (нет таких в этом периоде)")
    for tin, name, s, k in clean[:n]:
        _print_row(tin, name, s, k)

    # 4. Узлы в нетривиальных циклах (SCC > 1)
    print("\n[4] В НЕТРИВИАЛЬНЫХ ЦИКЛАХ (SCC > 1) — взаимная торговля:")
    cycles = []
    for comp in nx.strongly_connected_components(G):
        if len(comp) <= 1:
            continue
        cycles.append(comp)
    if not cycles:
        print("    (нетривиальных циклов в графе не найдено)")
    cycles.sort(key=lambda c: -len(c))
    for i, comp in enumerate(cycles[:n], start=1):
        comp_l = sorted(comp)
        print(f"    Цикл #{i} (размер {len(comp_l)}):")
        for m in comp_l[:3]:
            nm = short_name(G.nodes[m].get("volt_name"))
            s = sum(w for _, _, w in G.out_edges(m, data="weight") if w)
            print(f"      {m:>13}  {nm:<35}  kz={kz[m]:.2f}  продажи: {fmt_money(s)}")
        if len(comp_l) > 3:
            print(f"      … и ещё {len(comp_l)-3}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _parse_targets(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Прототип расчёта индекса КС")
    parser.add_argument("--days", type=int, default=90,
                        help="Глубина периода в днях (default: 90)")
    parser.add_argument("--target", type=str, default=None,
                        help="Один BIN для детального профиля (alias для --targets)")
    parser.add_argument("--targets", type=str, default=None,
                        help="Список BIN'ов через запятую: --targets 180640000680,123456789021")
    parser.add_argument("--top", type=int, default=10,
                        help="Размер топа в сводных таблицах (default: 10)")
    parser.add_argument("--list-cases", action="store_true",
                        help="Показать меню рекомендованных BIN'ов по архетипам и выйти")
    parser.add_argument("--no-distribution", action="store_true",
                        help="Не печатать гистограмму kz по всему графу")
    parser.add_argument("--no-top", action="store_true",
                        help="Не печатать топ-N импортно-зависимых")
    args = parser.parse_args()

    try:
        df_edges = load_edges(days=args.days)
    except (SQLAlchemyError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        return 2

    if df_edges.empty:
        print("[WARN] Нет рёбер за период.")
        return 0

    G = build_graph(df_edges)
    if G.number_of_nodes() == 0:
        print("[WARN] Граф пуст после фильтра.")
        return 0

    enrich_with_voltdb(G)

    section("ЗАПУСК ИТЕРАЦИОННОГО РАСЧЁТА kz_content")
    kz = compute_kz_content(G)

    # Агрегат — главная цифра для бизнеса
    show_aggregate_economy(kz, G)

    if not args.no_distribution:
        show_distribution(kz, G)
    if not args.no_top:
        show_top_import_dependent(kz, G, top_n=args.top)

    if args.list_cases:
        list_cases(kz, G, n=args.top)
        return 0

    # Список BIN'ов для детального анализа
    targets = _parse_targets(args.targets)
    if not targets and args.target:
        targets = [args.target.strip()]
    if not targets:
        auto = auto_pick_target(kz, G)
        if auto:
            targets = [auto]
            print(f"\n[INFO] --targets не задан, авто-подбор: {auto}")

    if not targets:
        print("\n[WARN] Не нашли BIN для детального анализа.")
        return 0

    for t in targets:
        analyze_target(kz, G, t)

    return 0


if __name__ == "__main__":
    sys.exit(main())
