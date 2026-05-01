# Диагностика проблем

Шпаргалка по частым ошибкам и как их быстро локализовать.

## Подключение к MySQL

### Симптом: `OperationalError: (1045, "Access denied")`

Кажется очевидным, но: **проверьте `.env`**. Особенно если в пароле
есть символы `$`, `@`, `#` — `quote_plus` в `build_connection_url()`
их экранирует, но если вы скопировали пароль с лишним символом — пиши
пропало.

```bash
docker compose run --rm echo-engine python -c \
  "from main import build_connection_url; print(build_connection_url())"
```

Скрипт распечатает финальный URL. Проверьте, что хост, порт, имя БД и
пользователь верные. **Пароль будет URL-encoded** — это нормально.

### Симптом: `OperationalError: (2003, "Can't connect")`

Сеть. Из контейнера не виден `MYSQL_HOST`. Проверьте:

```bash
docker compose run --rm echo-engine sh -c "nc -zv $MYSQL_HOST $MYSQL_PORT"
```

Если `Connection refused` — VPN отвалился или порт не открыт. Если
`unknown host` — DNS не резолвится, попробуйте подставить IP.

### Симптом: запрос `EDGES_QUERY` идёт минутами

На большом периоде (год+) это нормально. Чтобы убедиться, что используется
правильный индекс:

```sql
EXPLAIN SELECT
  h.seller_tin AS source, h.customer_tin AS target,
  SUM(d.total_price_without_tax) AS weight,
  COUNT(DISTINCT h.invoice_id) AS invoice_count
FROM <headers_table> h
INNER JOIN <lines_table> d ON d.invoice_id = h.invoice_id
WHERE d.turnover_date >= '2025-01-01' AND d.turnover_date < '2026-01-01'
  AND h.seller_tin IS NOT NULL AND h.customer_tin IS NOT NULL
GROUP BY h.seller_tin, h.customer_tin;
```

В `EXPLAIN`-плане для строк должен использоваться составной индекс по
`(seller_tin, customer_tin, turnover_date)` или `(turnover_date)`.

## Подключение к VoltDB

### Симптом: `ConnectionError: Could not connect to any host`

Проверьте `VOLTDB_PORT`. Частая ошибка — указать `8080` (HTTP-API)
вместо `21212` (native protocol). Драйвер `voltdbclient` использует
**только native protocol**.

### Симптом: `VoltDBConfigError: VOLTDB_HOSTS не задан`

В `.env` не указаны переменные. Скопируйте из `.env.example`:

```ini
VOLTDB_HOSTS=<VOLTDB_HOSTS>
VOLTDB_PORT=<VOLTDB_PORT>
VOLTDB_USER=<VOLTDB_USER>
VOLTDB_PASSWORD=<VOLTDB_PASSWORD>
```

### Симптом: `SQL error while compiling query: Error in "GROUP BY 1"`

VoltDB **не поддерживает позиционные аргументы в GROUP BY**. Замените
номер колонки на её имя:

```sql title="Не работает"
SELECT resident, COUNT(*) FROM <taxpayer_table> GROUP BY 1
```

```sql title="Работает"
SELECT resident, COUNT(*) FROM <taxpayer_table> GROUP BY resident
```

### Симптом: lookup пустой, хотя BIN'ы есть в справочнике

99% случаев — **сломалась нормализация BIN**. Проверьте, что в
`pd.read_sql` указан `dtype={"source": "string", "target": "string"}`,
иначе ведущие нули потерялись.

Быстрая проверка:

```bash
docker compose run --rm echo-engine python -c "
from volt_resolver import _pad
print(repr(_pad(40000537)))     # ожидаем '000040000537'
print(repr(_pad('40000537')))   # ожидаем '000040000537'
"
```

См. подробное обсуждение в [Нормализации BIN](../data-sources/bin-normalization.md).

## Расчёт kz_content

### Симптом: «Не сошлось за 500 итераций»

Маловероятно на штатных данных, но возможно если:

1. Есть очень крупный SCC (> 1000 узлов в одном цикле) с пограничными значениями;
2. Есть ребра с `weight = 0` (фильтр пропустил их). Проверьте `valid` в `build_graph`.

Что делать:

- Поднять `max_iter` (например, до 2000) или ослабить `tol` до `1e-5`;
- Запустить `explore.py` и посмотреть размеры SCC.

### Симптом: «Все kz = 1.0»

Признак того, что обогащение из VoltDB не сработало — в графе нет ни одного
нерезидента. Проверки:

```bash
docker compose run --rm echo-engine python -c "
from voltdb_client import VoltDBClient
with VoltDBClient.from_env() as v:
    # Имя таблицы и колонки берутся из конфигурации.
    print(v.query('SELECT COUNT(*) FROM <taxpayer_table> WHERE resident = 0'))
"
```

Должно вернуть число > 0. Если 0 — данные в VoltDB не загружены, или у
вашего пользователя нет прав.

Также проверьте логи `enrich_with_voltdb()` — там должно быть «нерезидентов: > 0».
Если 0 — проверяйте нормализацию BIN.

## Docker

### Симптом: `permission denied while trying to connect to the Docker daemon`

Docker daemon не запущен или ваш пользователь не в группе `docker`.
На macOS — открыть Docker Desktop. На Linux:

```bash
sudo usermod -aG docker $USER
# затем перелогиниться
```

### Симптом: контейнер сразу падает с кодом 0

Это нормально — `python kz_index.py` отрабатывает и завершается.
**Это batch-скрипт, а не сервис**. Если хотите оставить для отладки
работающий контейнер:

```bash
docker compose run --rm echo-engine bash
```

### Симптом: изменения в коде не подхватываются

Проверьте volume в `docker-compose.yml`:

```yaml
echo-engine:
  volumes:
    - .:/app
```

Должно быть смонтировано. Если нет — пересобрать:

```bash
docker compose build
```

## Документация

### Симптом: `docker compose up docs` падает с `Error parsing mkdocs.yml`

Проверьте отступы в `mkdocs.yml` — YAML чувствителен к пробелам.
И что версия в `image: squidfunk/mkdocs-material:9.5.39` существует
(если нет — поменяйте на `latest`).

### Симптом: mermaid-диаграммы не рендерятся

В `mkdocs.yml` должна быть секция:

```yaml
markdown_extensions:
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
```

Если её нет — добавьте.

### Симптом: формулы LaTeX не рендерятся

В `mkdocs.yml` должна быть:

```yaml
markdown_extensions:
  - pymdownx.arithmatex:
      generic: true
extra_javascript:
  - https://unpkg.com/mathjax@3/es5/tex-mml-chtml.js
```

Перезапустите `docker compose up docs`.

## Где взять помощь

1. **EDA**: запустить `explore.py` и посмотреть на блок «КАЧЕСТВО ДАННЫХ».
2. **Точечная проверка**: `check_company.py <BIN> 90`.
3. **Discovery VoltDB**: `voltdb_explore.py`.
4. **Логи**: всё пишется в stdout. Перенаправьте в файл при сложной отладке:

    ```bash
    docker compose run --rm echo-engine python kz_index.py --days 90 \
      --list-cases > debug.log 2>&1
    ```
