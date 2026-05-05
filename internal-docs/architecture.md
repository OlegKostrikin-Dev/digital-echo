# Архитектура

## Контекст

Движок `digital-echo-core` — это batch-обработчик: за один запуск он
вытягивает срез транзакций за период, обогащает его справочной информацией
и считает индекс КС для всех узлов графа.

Все взаимодействия с внешними системами идут через два протокола:

- **MySQL** — единственный источник транзакций (ЭСФ-документы);
- **VoltDB** — единственный источник справочной информации о налогоплательщиках.

```mermaid
C4Context
    title Контекст digital-echo-core

    Person(analyst, "Аналитик", "Консольно запускает расчёты, готовит демо")
    Person(architect, "Архитектор", "Интерпретирует результаты, ставит задачи")

    System(echo, "digital-echo-core", "Расчёт индекса КС по графу B2B-транзакций")

    System_Ext(esf, "MySQL", "ЭСФ-документы<br/>заголовки и строки")
    System_Ext(volt, "VoltDB", "Справочник налогоплательщиков<br/>с признаком резидентности")

    Rel(analyst, echo, "запускает<br/>docker compose run")
    Rel(echo, esf, "SELECT JOIN<br/>агрегация по seller/customer")
    Rel(echo, volt, "@AdHoc IN-lookup<br/>BIN → resident")
    Rel(echo, analyst, "консольный отчёт")
    Rel(architect, analyst, "формулирует кейсы")
```

## Контейнеры

```mermaid
C4Container
    title Контейнеры digital-echo-core

    Container(web, "Web UI", "React + Vite (port 3000)", "Интерактивный интерфейс для аналитика")
    Container(api, "Backend API", "FastAPI + uvicorn (port 8000)", "REST + аналитическое ядро")
    Container(cli, "CLI", "python -m core.*", "Запуски без web для скриптов и cron")
    Container(docs, "Документация", "MkDocs Material (port 8080)", "Эта документация")

    ContainerDb(mysql, "MySQL", "InnoDB", "~1.3M документов ЭСФ")
    ContainerDb(volt, "VoltDB", "VoltDB 14.x", "Справочник BIN → resident")

    Rel(web, api, "REST", "JSON over HTTPS")
    Rel(api, mysql, "JOIN заголовков и строк ЭСФ", "SQLAlchemy + PyMySQL")
    Rel(api, volt, "lookup BIN → resident", "voltdbclient @AdHoc")
    Rel(cli, mysql, "тот же JOIN", "напрямую через core.engine")
    Rel(cli, volt, "тот же lookup", "напрямую через core.engine")
```

## Внутренняя структура

```mermaid
flowchart TB
    subgraph EXT[Внешние данные]
      MySQL[(MySQL<br/>ЭСФ-документы)]
      Volt[(VoltDB<br/>справочник<br/>налогоплательщиков)]
    end

    subgraph BACKEND[services/backend/src]
      direction TB
      FastAPIApp[main.py<br/>FastAPI app]
      Routes[api/routes.py<br/>HTTP endpoints]
      Schemas[api/schemas.py<br/>Pydantic]
      Deps[deps.py<br/>GraphState in-memory]

      subgraph CORE[core/ — аналитическое ядро]
        Edges[edges.py<br/>SQL]
        VoltCli[voltdb_client.py]
        VoltRes[volt_resolver.py]
        Engine[engine.py<br/>compute_state]
        Analytics[analytics.py<br/>data-функции]
        KZCli[kz_index.py<br/>CLI с печатью]
      end

      FastAPIApp --> Routes
      Routes --> Deps
      Routes --> Analytics
      Deps --> Engine
      Engine --> Edges
      Engine --> VoltRes
      VoltRes --> VoltCli
      KZCli --> Engine
    end

    subgraph FRONTEND[apps/web/src]
      direction TB
      App[App.tsx + Layout]
      Pages[pages/<br/>HomePage, CasesPage,<br/>SearchPage, CompanyPage]
      ApiClient[api.ts<br/>fetch wrapper]
      App --> Pages
      Pages --> ApiClient
    end

    MySQL --> Edges
    Volt --> VoltCli

    ApiClient -- "JSON" --> Routes
    KZCli -->|stdout| Out[Консольный<br/>отчёт]
```

## Поток данных одного прогона

```mermaid
sequenceDiagram
    autonumber
    participant U as Пользователь
    participant K as kz_index.py
    participant M as MySQL
    participant V as VoltDB
    participant G as NetworkX DiGraph

    U->>K: docker compose run --rm echo-engine ...
    K->>M: SELECT JOIN agg by (seller_tin, customer_tin)
    M-->>K: ~100K рёбер за 90 дней
    K->>K: фильтр weight > 0
    K->>G: build_graph(df_edges)
    Note over G: ~100K узлов,<br/>~106K рёбер
    K->>V: SELECT справочник WHERE tin IN (...) (chunks по 1000)
    V-->>K: BIN → (resident, name, state, type)
    K->>G: enrich_with_voltdb(): set is_non_resident, volt_name
    K->>G: compute_kz_content(): fixed-point
    Note over G: 244 итерации до tol=1e-7
    K->>U: распределение, топ-N, --targets профили
```

## Стейтлес и идемпотентность

Движок не хранит состояние между запусками. Каждый прогон **полностью
пересчитывает** граф и индекс. Это даёт два важных свойства:

- **Идемпотентность**: одинаковые входные параметры → одинаковый результат.
- **Отсутствие миграций**: не нужно дампить промежуточные таблицы,
  не нужно следить за версиями схемы.

Цена — 80 секунд на полный прогон при 100K узлов / 90-дневный период.
Это **сознательный размен**: на демо-фазе скорость не важна, а
повторяемость — критична.

См. [ADR-001](decisions/001-graph-engine.md) о выборе in-memory подхода.

## Конфигурация и секреты

Все секреты живут в `.env` (не в git). Шаблон — `.env.example`:

```ini
# MySQL (источник транзакций)
MYSQL_HOST=<MYSQL_HOST>
MYSQL_PORT=<MYSQL_PORT>
MYSQL_USER=<MYSQL_USER>
MYSQL_PASSWORD=<MYSQL_PASSWORD>
MYSQL_DATABASE=<MYSQL_DATABASE>

# VoltDB (справочник резидентности)
VOLTDB_HOSTS=<VOLTDB_HOSTS>
VOLTDB_PORT=<VOLTDB_PORT>
VOLTDB_USER=<VOLTDB_USER>
VOLTDB_PASSWORD=<VOLTDB_PASSWORD>
```

`build_connection_url()` в `main.py` собирает MySQL-URL с экранированием
спецсимволов (`quote_plus` — на случай `$`, `@`, `-` в пароле).

`VoltDBClient.from_env()` читает `VOLTDB_*` и поддерживает несколько хостов
через запятую (например, `VOLTDB_HOSTS=host1,host2`).

## Что мы намеренно НЕ строим (пока)

- :material-close: **БД-кэш промежуточных результатов.** Прогон должен быть
  чистым, без серых зон «а это в кэше или свежее».
- :material-close: **Очередь и оркестратор.** Один скрипт — одна команда.
  Когда понадобится планировщик — обернём в Airflow/Prefect.
- :material-close: **Отдельный API-слой.** Web-морда (по эскизам аналитика)
  будет читать те же модули напрямую — без REST-прослойки.
- :material-close: **Распределённый компьют.** 100K-200K узлов спокойно
  держатся в памяти. Если понадобится 10M+ — переедем на
  graph-tool/igraph или на Spark GraphFrames.

См. [Roadmap](../../docs/roadmap.md) о том, куда планируем двигаться.
