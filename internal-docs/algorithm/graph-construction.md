# Граф транзакций

Граф $G = (V, E, w)$ строится из двух MySQL-таблиц InnoDB:

- `<headers_table>` — заголовки ЭСФ-документов;
- `<lines_table>` — детализация строк (с `total_price_without_tax` и
  `turnover_date`).

Конкретные имена таблиц задаются в коде модуля
`services/backend/src/core/edges.py` и в `.env`-конфигурации (в публичной
документации они не приводятся).

## SQL-запрос построения рёбер (псевдо-SQL)

```sql title="EDGES_QUERY"
SELECT
    h.seller_tin                    AS source,
    h.customer_tin                  AS target,
    SUM(d.total_price_without_tax)  AS weight,
    COUNT(DISTINCT h.invoice_id)    AS invoice_count
FROM <headers_table>           AS h
INNER JOIN <lines_table>       AS d
        ON d.invoice_id = h.invoice_id
WHERE d.turnover_date >= :date_from
  AND d.turnover_date <  :date_to
  AND h.seller_tin   IS NOT NULL
  AND h.customer_tin IS NOT NULL
  AND h.seller_tin <> ''
  AND h.customer_tin <> ''
GROUP BY h.seller_tin, h.customer_tin
```

## Что мы оптимизируем

| Решение | Почему |
|---|---|
| Группируем сразу по `(seller_tin, customer_tin)` | Уменьшает объём данных в Python в 10–20 раз: вместо строк мы тянем агрегаты. |
| `SUM(d.total_price_without_tax)` без НДС | Чтобы НДС не двойной счётчик в цепочке: купил с НДС → продал с НДС. |
| `COUNT(DISTINCT h.invoice_id)` | Один документ = один контракт, важна повторность отношений. |
| Фильтр по `d.turnover_date` | Используем составной индекс по `(seller_tin, customer_tin, turnover_date)`. |
| `INNER JOIN` на `invoice_id` | Гарантирует, что мы не выберем «висящих» строк. |

## Структура полученных рёбер

| Колонка | Тип | Что значит |
|---|---|---|
| `source` | string | BIN продавца (узел-исток ребра) |
| `target` | string | BIN покупателя (узел-приёмник ребра) |
| `weight` | float | Суммарная закупка по этому направлению, ₸ без НДС |
| `invoice_count` | int | Количество уникальных документов между парой |

!!! warning "Критично: dtype string для BIN"
    В MySQL `seller_tin` / `customer_tin` хранятся как `bigint unsigned`.
    Если pandas прочитает их как `int64`, **потеряются ведущие нули**.

    Поэтому при `pd.read_sql` мы явно указываем:

    ```python
    BIN_DTYPE = {"source": "string", "target": "string"}
    df = pd.read_sql(EDGES_QUERY, conn, params=..., dtype=BIN_DTYPE)
    ```

    Подробнее — [Нормализация BIN](../data-sources/bin-normalization.md).

## Фильтрация на стороне Python

После получения сырых рёбер из MySQL мы дополнительно фильтруем
в `build_graph()`:

```python
valid = df_edges[df_edges["weight"] > 0].copy()
```

Это убирает:

- **Корректировки и возвраты** с отрицательным `total_price_without_tax`
  (на 90-дневной выборке — около 6 рёбер);
- **Нулевые транзакции** (на 90 днях — около 467 рёбер).

Self-loops (`A → A`) не отфильтровываются специально, но их в графе
буквально единицы и они не влияют на сходимость.

## Построение `nx.DiGraph`

```python
G = nx.from_pandas_edgelist(
    valid,
    source="source", target="target",
    edge_attr=["weight", "invoice_count"],
    create_using=nx.DiGraph,
)
```

Получаем направленный граф с двумя атрибутами на каждом ребре.
**Узлы** появляются автоматически — их множество = объединение `source` и
`target` из всех рёбер.

## Оценка размерности графа

На 90-дневной выборке ноября 2025 – января 2026:

| Метрика | Значение |
|---|---|
| Документов в исходных заголовках ЭСФ | 1 324 389 |
| Рёбер графа после агрегации | ~106 773 |
| Уникальных узлов | ~100 516 |
| Плотность (`E / V²`) | 0.001% |
| Слабо связных компонент | 19 (гигантская — 100% узлов) |
| Нетривиальных SCC (циклы) | 18 |
| Глубина цепочек (через конденсацию) | 6 уровней |

Подробный EDA — `explore.py`.

## Узловые атрибуты

После построения графа в `enrich_with_voltdb()` мы дописываем атрибуты узлов:

| Атрибут | Тип | Источник | Что значит |
|---|---|---|---|
| `is_non_resident` | bool / None | справочник налогоплательщиков (`resident`) | True для нерезидента, None если BIN не нашёлся в справочнике |
| `volt_name` | str / None | справочник налогоплательщиков (`name_ru`) | Юридическое наименование |

```python
G.nodes[v]["is_non_resident"] = bool_or_none
G.nodes[v]["volt_name"] = "ТОО «Х»"
```

Эти атрибуты используются в [расчёте kz_content](kz-content.md) и в
[аналитических конусах](analytical-views.md).
