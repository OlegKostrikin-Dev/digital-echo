"""digital-echo-core: EDA выгруженного среза рёбер графа B2B-транзакций.

Скрипт отвечает на вопросы:
  1. Какова структура графа: |V|, |E|, плотность, связность.
  2. Распределение веса (сумм) и invoice_count.
  3. Кто посредник (узлы, которые одновременно продают и покупают)?
  4. Есть ли циклы, петли, мультирёбра?
  5. Каковы топ-узлы по обороту, in/out-степени?
  6. Какова длина цепочек поставок (важно для индекса КС)?
"""

import random
import sys

import networkx as nx
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from .edges import EDGES_QUERY, build_connection_url, get_default_period


# Чтобы не терять ведущие нули в БИН — приводим к строке
BIN_DTYPE = {"source": "string", "target": "string"}


def fmt(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ")


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def load_edges(days: int) -> pd.DataFrame:
    load_dotenv()
    url = build_connection_url()
    date_from, date_to = get_default_period(days=days)
    print(f"[INFO] Период: {date_from} -> {date_to} ({days} дней)")

    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conn:
        df = pd.read_sql(
            EDGES_QUERY, conn,
            params={"date_from": date_from, "date_to": date_to},
            dtype=BIN_DTYPE,
        )
    return df


def analyze_dataframe(df: pd.DataFrame) -> None:
    section("1. БАЗОВАЯ СТАТИСТИКА РЁБЕР")
    print(f"Рёбер всего:           {len(df)}")
    print(f"Уникальных source:     {df['source'].nunique()}")
    print(f"Уникальных target:     {df['target'].nunique()}")
    nodes = pd.concat([df['source'], df['target']]).unique()
    print(f"Уникальных узлов |V|:  {len(nodes)}")

    section("2. РАСПРЕДЕЛЕНИЕ ВЕСА (СУММЫ БЕЗ НДС)")
    print(df['weight'].describe().apply(fmt).to_string())
    print(f"\nСумма всего оборота:   {fmt(df['weight'].sum())} ₸")

    section("3. РАСПРЕДЕЛЕНИЕ INVOICE_COUNT")
    print(df['invoice_count'].describe().to_string())
    regular = (df['invoice_count'] >= 5).sum()
    one_off = (df['invoice_count'] == 1).sum()
    print(f"\nРазовых сделок (count=1):     {one_off}")
    print(f"Регулярных пар (count>=5):    {regular}")


# Порог размера, выше которого тяжёлые алгоритмы (диаметр, eigenvector centrality)
# не запускаются — иначе O(V*(V+E)) повесит контейнер.
HEAVY_ALGO_NODE_LIMIT = 5_000


def _approx_diameter_sample(H: nx.Graph, sample_size: int = 64) -> int:
    """Оценка диаметра через несколько случайных BFS (нижняя граница)."""
    nodes = list(H.nodes)
    if len(nodes) <= sample_size:
        sample = nodes
    else:
        sample = random.sample(nodes, sample_size)
    best = 0
    for s in sample:
        lengths = nx.single_source_shortest_path_length(H, s)
        if lengths:
            best = max(best, max(lengths.values()))
    return best


def analyze_graph(df: pd.DataFrame) -> None:
    G = nx.from_pandas_edgelist(
        df, source='source', target='target',
        edge_attr=['weight', 'invoice_count'],
        create_using=nx.DiGraph,
    )

    section("4. СТРУКТУРА ГРАФА")
    n, m = G.number_of_nodes(), G.number_of_edges()
    print(f"|V| (узлы):            {n}")
    print(f"|E| (рёбра):           {m}")
    if n > 1:
        density = m / (n * (n - 1))
        print(f"Плотность:             {density:.5f}  ({density*100:.3f}%)")
    self_loops = nx.number_of_selfloops(G)
    print(f"Петель (A->A):         {self_loops}")

    section("5. КОМПОНЕНТЫ СВЯЗНОСТИ")
    weak = sorted(nx.weakly_connected_components(G), key=len, reverse=True)
    strong = sorted(nx.strongly_connected_components(G), key=len, reverse=True)
    print(f"Слабо связных компонент:    {len(weak)}")
    if weak:
        print(f"  Размеры топ-5:           {[len(c) for c in weak[:5]]}")
        print(f"  Гигантская компонента:   {len(weak[0])}/{n} = {len(weak[0])/n*100:.1f}% узлов")
    print(f"Сильно связных компонент:   {len(strong)}")
    nontrivial_strong = [c for c in strong if len(c) > 1]
    print(f"  Нетривиальных (>1 узла):  {len(nontrivial_strong)}")
    if nontrivial_strong:
        sizes = sorted((len(c) for c in nontrivial_strong), reverse=True)[:10]
        print(f"  Размеры топ-10 циклов:    {sizes}")
        print(f"  -> это потенциальные ЦИКЛЫ в торговых отношениях")

    section("6. РОЛИ УЗЛОВ")
    sellers = set(df['source'].unique())
    buyers = set(df['target'].unique())
    pure_sellers = sellers - buyers
    pure_buyers = buyers - sellers
    intermediaries = sellers & buyers
    print(f"Только продавцы (out>0, in=0):       {len(pure_sellers)}  -> 'источники' стоимости")
    print(f"Только покупатели (out=0, in>0):     {len(pure_buyers)}   -> 'стоки' (конечные потребители)")
    print(f"Посредники (продают И покупают):     {len(intermediaries)} -> ключевые узлы для индекса КС")
    if n:
        print(f"Доля посредников от |V|:             {len(intermediaries)/n*100:.2f}%")

    section("7. ТОП-10 УЗЛОВ ПО ОБОРОТУ (out-strength: сколько продали)")
    out_strength = df.groupby('source')['weight'].sum().sort_values(ascending=False).head(10)
    out_count = df.groupby('source').size()
    top_sellers = pd.DataFrame({
        'BIN': out_strength.index,
        'sales_sum': out_strength.values,
        'unique_buyers': [out_count.loc[t] for t in out_strength.index],
    })
    top_sellers['sales_sum'] = top_sellers['sales_sum'].apply(fmt)
    print(top_sellers.to_string(index=False))

    section("8. ТОП-10 УЗЛОВ ПО ЗАКУПКАМ (in-strength)")
    in_strength = df.groupby('target')['weight'].sum().sort_values(ascending=False).head(10)
    in_count = df.groupby('target').size()
    top_buyers = pd.DataFrame({
        'BIN': in_strength.index,
        'purchase_sum': in_strength.values,
        'unique_sellers': [in_count.loc[t] for t in in_strength.index],
    })
    top_buyers['purchase_sum'] = top_buyers['purchase_sum'].apply(fmt)
    print(top_buyers.to_string(index=False))

    section("9. ГЛУБИНА ЦЕПОЧЕК ПОСТАВОК (через конденсацию SCC)")
    # Конденсация: каждый SCC схлопывается в одну вершину => получается DAG.
    # Длина самого длинного пути в этом DAG — это РЕАЛЬНАЯ глубина цепочки
    # поставок в "макро-структуре" графа (даже при наличии циклов).
    C = nx.condensation(G)
    cn, cm = C.number_of_nodes(), C.number_of_edges()
    print(f"Узлов в конденсации:        {cn}  (схлопнули {n - cn} узлов в SCC)")
    print(f"Рёбер в конденсации:        {cm}")
    if cn > 0 and cm > 0:
        try:
            longest_path_len = nx.dag_longest_path_length(C)
            print(f"Самая длинная цепочка:      {longest_path_len} уровней")
            print(f"  (т.е. эхо может пройти максимум через {longest_path_len + 1} узлов)")
        except Exception as exc:
            print(f"[WARN] longest_path не посчитан: {exc}")

        # Источники и стоки в DAG-конденсации
        if cn <= 200_000:
            source_nodes = [v for v in C.nodes if C.in_degree(v) == 0]
            sink_nodes = [v for v in C.nodes if C.out_degree(v) == 0]
            print(f"Источников (без входящих):  {len(source_nodes)}")
            print(f"Стоков (без исходящих):     {len(sink_nodes)}")
    else:
        print("Конденсация пустая или тривиальна — глубину не измерить.")

    section("10. ДИАМЕТР ГИГАНТСКОЙ КОМПОНЕНТЫ")
    if not weak:
        print("Слабых компонент нет.")
    else:
        H = G.subgraph(weak[0]).to_undirected()
        h_n = H.number_of_nodes()
        if h_n <= 1:
            print(f"Гигантская компонента слишком мала ({h_n} узлов).")
        elif h_n <= HEAVY_ALGO_NODE_LIMIT:
            try:
                diam = nx.diameter(H)
                print(f"Точный диаметр (undirected): {diam}")
            except Exception as exc:
                print(f"[WARN] Диаметр не посчитан: {exc}")
        else:
            print(f"Точный диаметр пропущен: |V|={h_n} > {HEAVY_ALGO_NODE_LIMIT} (O(V*(V+E)) слишком дорого).")
            approx = _approx_diameter_sample(H, sample_size=64)
            print(f"Оценка снизу через 64 случайных BFS: >= {approx}")

    section("11. КАЧЕСТВО ДАННЫХ")
    neg = (df['weight'] < 0).sum()
    zero = (df['weight'] == 0).sum()
    self_loop_rows = (df['source'] == df['target']).sum()
    print(f"Рёбер с weight < 0:    {neg}  (возможно, корректировки/возвраты)")
    print(f"Рёбер с weight = 0:    {zero}")
    print(f"Self-loops (A->A):     {self_loop_rows}")
    if neg:
        worst = df.nsmallest(3, 'weight')[['source', 'target', 'weight', 'invoice_count']]
        print("Топ-3 самых отрицательных ребра:")
        print(worst.to_string(index=False))

    section("12. ВЕРДИКТ ПО ПРИГОДНОСТИ ДАННЫХ")
    verdict = []
    intermediary_share = len(intermediaries) / n if n else 0
    if m < 500:
        verdict.append(f"|E| = {m} < 500 — данных мало для статистически значимого графа.")
    if intermediary_share < 0.05:
        verdict.append(
            f"Посредников всего {intermediaries.__len__()} ({intermediary_share*100:.2f}% от |V|) — "
            "цепочки поставок мелкие, эхо погаснет на 1–2 шагах."
        )
    if not nontrivial_strong:
        verdict.append("Циклов в графе нет — нельзя обкатать алгоритмы детекции схем.")
    if weak and len(weak[0]) / n < 0.3:
        verdict.append(
            f"Гигантская компонента покрывает лишь {len(weak[0])/n*100:.1f}% узлов — "
            "граф фрагментирован."
        )
    if cn and cm:
        try:
            depth = nx.dag_longest_path_length(C)
            if depth < 3:
                verdict.append(
                    f"Глубина цепочек поставок = {depth} — это меньше 3 уровней, "
                    "для расчёта индекса КС нужно минимум 3–5 уровней."
                )
        except Exception:
            pass

    if verdict:
        print("Замечания:")
        for v in verdict:
            print(f"  - {v}")
        print("\n=> Рекомендация: догенерировать данные через API ИС ЭСФ.")
    else:
        print("Данные пригодны для прототипа алгоритмов индекса КС.")


def main(days: int = 30) -> int:
    try:
        df = load_edges(days=days)
    except (SQLAlchemyError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        return 2

    if df.empty:
        print("[WARN] Данных за период нет.")
        return 0

    analyze_dataframe(df)
    analyze_graph(df)
    return 0


if __name__ == "__main__":
    days_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    sys.exit(main(days=days_arg))
