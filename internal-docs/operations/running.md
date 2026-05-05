# Запуск и API

## Web UI

После `docker compose up -d` открыть http://localhost:3000.

| Страница | URL | Что показывает |
|---|---|---|
| Главная | `/` | Статус, кнопка «Пересчитать», агрегат, мета-информация |
| Меню кейсов | `/cases` | 4 архетипа: импортёры, зависимые, чистые, в циклах |
| Поиск | `/search` | Ввод BIN → переход на профиль |
| Профиль компании | `/company/:bin` | Карточка + backward-конус + forward-конус |

### Типичный сценарий демо

1. Открыть http://localhost:3000.
2. На главной выставить `Период = 90`, нажать **«Пересчитать индекс»**.
3. Подождать ~80 секунд — увидите агрегат «X% импорта в обороте».
4. Перейти на **«Кейсы»** — видны 4 категории компаний.
5. Кликнуть на любой BIN — открывается профиль с обоими конусами.

## REST API

Backend слушает на http://localhost:8000.

Интерактивная документация Swagger: **http://localhost:8000/docs**

### Эндпоинты

| Метод | URL | Что делает |
|---|---|---|
| `GET` | `/api/health` | health-check |
| `GET` | `/api/state` | Текущее состояние расчёта (idle / computing / ready / error) |
| `POST` | `/api/recompute` | Запустить пересчёт. Тело: `{"days": 90, "force": false}` |
| `GET` | `/api/aggregate` | Агрегат: % импорта в обороте |
| `GET` | `/api/distribution` | Гистограмма kz по всему графу |
| `GET` | `/api/top-importers?n=10` | Топ компаний по импортному вкладу |
| `GET` | `/api/list-cases?n=5` | Меню по 4 архетипам |
| `GET` | `/api/company/{bin}` | Полный профиль компании |

Все эндпоинты возвращают JSON. Эндпоинты, требующие готового графа,
вернут **HTTP 409**, если расчёт ещё не запущен.

### Пример работы

```bash
# 1) Запустить расчёт
curl -X POST http://localhost:8000/api/recompute \
  -H "Content-Type: application/json" \
  -d '{"days": 90}'
# Ждать ~80 секунд

# 2) Получить агрегат
curl http://localhost:8000/api/aggregate

# 3) Профиль компании
curl http://localhost:8000/api/company/180640000680
```

### CORS

По умолчанию backend разрешает запросы с `localhost:3000`,
`localhost:5173`, `127.0.0.1:3000`. Изменить через переменную окружения
`CORS_ORIGINS` (см. `docker-compose.yml`).

## CLI (без web)

Все CLI-скрипты сохранены и работают через `python -m core.<имя>`.
Запуск через `docker compose run --rm backend ...`:

### `core.kz_index` — главный аналитический CLI

```bash
docker compose run --rm backend python -m core.kz_index --days 90 --list-cases
```

| Параметр | Тип | По умолчанию | Что делает |
|---|---|---|---|
| `--days` | int | 90 | Глубина периода в днях |
| `--targets` | str | — | Список BIN'ов через запятую |
| `--target` | str | — | Один BIN (alias) |
| `--top` | int | 10 | Размер топа |
| `--list-cases` | flag | false | Меню кандидатов |
| `--no-distribution` | flag | false | Без гистограммы |
| `--no-top` | flag | false | Без топ-N |

### `core.explore` — EDA по графу

```bash
docker compose run --rm backend python -m core.explore 90
```

### `core.check_company` — проверка одного BIN

```bash
docker compose run --rm backend python -m core.check_company 180640000680 90
```

### `core.voltdb_explore` — discovery VoltDB

```bash
docker compose run --rm backend python -m core.voltdb_explore
```

## Запуск отдельных сервисов

```bash
# Только backend (без web и docs)
docker compose up backend

# Только документация
docker compose up docs

# Полная пересборка backend
docker compose up --build backend

# Логи в реальном времени
docker compose logs -f backend
```

## Сборка статической документации

```bash
docker compose run --rm docs build
# Результат — папка site/, готова к деплою на S3 / GitHub Pages.
```
