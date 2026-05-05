# Установка и настройка

## Требования

| Компонент | Версия |
|---|---|
| Docker | 24.x+ |
| Docker Compose | v2 (встроенный в Docker Desktop) |
| Доступ к корпоративной MySQL с ЭСФ-документами | сетевой + пара логин/пароль |
| Доступ к корпоративной VoltDB со справочником | сетевой + пара логин/пароль |

Установка без Docker возможна (Python 3.11+ и Node.js 20+), но не
рекомендуется — все настройки ниже даны для Docker.

## Шаг 1. Получить репозиторий

```bash
git clone <repo-url> digital-echo-core
cd digital-echo-core
```

## Шаг 2. Заполнить `.env`

```bash
cp .env.example .env
# открыть .env в редакторе и подставить реальные значения
```

`.env.example`:

```ini
# MySQL — источник транзакций ЭСФ
MYSQL_HOST=<MYSQL_HOST>
MYSQL_PORT=<MYSQL_PORT>
MYSQL_USER=<MYSQL_USER>
MYSQL_PASSWORD=<MYSQL_PASSWORD>
MYSQL_DATABASE=<MYSQL_DATABASE>

# VoltDB — справочник резидентности
VOLTDB_HOSTS=<VOLTDB_HOSTS>
VOLTDB_PORT=<VOLTDB_PORT>
VOLTDB_USER=<VOLTDB_USER>
VOLTDB_PASSWORD=<VOLTDB_PASSWORD>
```

Реальные значения получает администратор корпоративной инфраструктуры —
**в публичной документации они не публикуются**.

!!! danger "Безопасность"
    `.env` уже добавлен в `.gitignore`. **Никогда не коммитьте его** —
    содержит креды от боевых баз.

## Шаг 3. Собрать образы

```bash
docker compose build
```

Что собирается:

| Образ | Базовый | Зачем |
|---|---|---|
| `backend` | `python:3.11-slim` | FastAPI + аналитическое ядро |
| `web`     | `node:20-alpine`   | Vite dev-сервер для React |
| `docs`    | `squidfunk/mkdocs-material` | Сервер документации |

Backend `requirements.txt`:

| Пакет | Версия | Назначение |
|---|---|---|
| `pandas` | 2.2.3 | DataFrame для рёбер графа |
| `networkx` | 3.4.2 | Движок графа |
| `SQLAlchemy` | 2.0.36 | SQL-слой |
| `PyMySQL` | 1.1.1 | MySQL драйвер |
| `python-dotenv` | 1.0.1 | Чтение `.env` |
| `voltdbclient` | 14.2.0 | Клиент VoltDB |
| `fastapi` | 0.115.5 | HTTP API |
| `uvicorn[standard]` | 0.32.1 | ASGI-сервер |

Frontend `package.json`:

| Пакет | Версия |
|---|---|
| `react` | 18.3 |
| `react-router-dom` | 6.27 |
| `vite` | 5.4 |
| `tailwindcss` | 3.4 |
| `typescript` | 5.6 |

## Шаг 4. Поднять окружение

```bash
docker compose up -d
```

Запускаются три сервиса:

| Сервис | Порт хоста | URL |
|---|---|---|
| `backend` | 8000 | http://localhost:8000/docs (Swagger) |
| `web` | 3000 | http://localhost:3000 (главная страница) |
| `docs` | 8080 | http://localhost:8080 (эта документация) |

Проверить, что всё ок:

```bash
curl http://localhost:8000/api/health
# → {"status":"ok"}
```

## Шаг 5. Запустить расчёт через web

1. Открыть http://localhost:3000
2. На главной указать `Период (дней)` и нажать «Пересчитать индекс»
3. Через ~80 секунд появятся агрегаты и ссылки на разделы
4. Перейти на `/cases` для списка архетипов или `/search` для поиска по BIN

## Шаг 6. Запустить расчёт через CLI (опционально)

```bash
docker compose run --rm backend python -m core.kz_index --days 90 --list-cases
```

Поддерживаются все те же флаги, что были в монолите. См. [CLI](running.md).

## Структура проекта

```text
digital-echo-core/
├── .env                              # секреты (не в git)
├── .env.example                      # шаблон секретов
├── .gitignore
├── docker-compose.yml                # backend + web + docs
├── mkdocs.yml                        # конфиг документации
│
├── services/
│   └── backend/                      # FastAPI + аналитическое ядро
│       ├── Dockerfile
│       ├── requirements.txt
│       └── src/
│           ├── main.py               # FastAPI app
│           ├── deps.py               # GraphState (in-memory)
│           ├── api/
│           │   ├── routes.py         # /api/* endpoints
│           │   └── schemas.py        # Pydantic
│           └── core/
│               ├── engine.py         # compute_state — полный прогон
│               ├── analytics.py      # data-функции для API
│               ├── kz_index.py       # CLI (с печатью)
│               ├── edges.py          # SQL для MySQL
│               ├── voltdb_client.py  # VoltDB адаптер
│               ├── volt_resolver.py  # BIN → resident
│               ├── explore.py        # EDA CLI
│               ├── check_company.py  # CLI на один BIN
│               └── voltdb_explore.py # discovery VoltDB
│
├── apps/
│   └── web/                          # React + Vite
│       ├── Dockerfile
│       ├── package.json
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── tailwind.config.js
│       ├── postcss.config.js
│       ├── index.html
│       └── src/
│           ├── main.tsx
│           ├── App.tsx
│           ├── api.ts
│           ├── types.ts
│           ├── components/
│           │   ├── Layout.tsx
│           │   └── StateBadge.tsx
│           └── pages/
│               ├── HomePage.tsx
│               ├── CasesPage.tsx
│               ├── SearchPage.tsx
│               └── CompanyPage.tsx
│
├── docs/                             # публичная MkDocs (методология)
│   ├── index.md
│   ├── algorithm/
│   └── data-sources/
│
└── internal-docs/                    # техническая документация (не в MkDocs)
    ├── README.md
    ├── architecture.md
    ├── operations/
    ├── algorithm/graph-construction.md
    ├── data-sources/
    └── decisions/
```

## Обновление при изменении кода

Volume `./services/backend/src:/app/src` смонтирован — uvicorn с
`--reload` сам подхватит изменения **в Python-коде**.

Volume `./apps/web:/app/apps/web` смонтирован — Vite сам перезагрузит
страницу **при изменении frontend-кода**.

Пересборка образа нужна только если поменялся `requirements.txt`,
`package.json` или `Dockerfile`:

```bash
docker compose build --no-cache
```
