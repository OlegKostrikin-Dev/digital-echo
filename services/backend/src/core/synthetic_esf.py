"""Генерация синтетических ЭСФ в отдельной MySQL database (invoice_search 1:1 invoice_search_advanced)."""

from __future__ import annotations

import argparse
import math
import os
import random
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .edges import build_synthetic_connection_url

# ──────────────────────────────────────────────────────────────────────────────
# КАТАЛОГ СИНТЕТИЧЕСКИХ КОМПАНИЙ
# Диапазон BIN 990_000_000_000+ не пересекается с реальными казахстанскими БИН.
# Ключ: BIN (int). Значение: name (str), is_nr (bool).
# ──────────────────────────────────────────────────────────────────────────────
SYNTHETIC_CATALOG: dict[int, dict] = {
    # ══════ ① НЕРЕЗИДЕНТЫ-ИМПОРТЁРЫ — продают товары/услуги в Казахстан ══════
    # Крупные (заводы, ТНК, сырьё) — avg ~11 млн ₸ × 200 инвойсов/год
    990_000_000_001: {"name": "Samsung Electronics Co. Ltd",      "is_nr": True},
    990_000_000_002: {"name": "Siemens AG",                       "is_nr": True},
    990_000_000_003: {"name": "Caterpillar Inc.",                  "is_nr": True},
    990_000_000_004: {"name": "General Electric Company",         "is_nr": True},
    990_000_000_005: {"name": "ABB Ltd.",                         "is_nr": True},
    # Средние (дистрибуция, техника) — avg ~8 млн ₸ × 50 инвойсов/год
    990_000_000_006: {"name": "Huawei Technologies Co. Ltd",      "is_nr": True},
    990_000_000_007: {"name": "Cisco Systems Inc.",               "is_nr": True},
    990_000_000_008: {"name": "Schneider Electric SE",            "is_nr": True},
    990_000_000_009: {"name": "Komatsu Ltd.",                     "is_nr": True},
    990_000_000_010: {"name": "Volvo Trucks Corporation",         "is_nr": True},
    990_000_000_011: {"name": "Nokia Networks OY",                "is_nr": True},
    990_000_000_012: {"name": "Ericsson AB",                      "is_nr": True},
    990_000_000_013: {"name": "Kärcher GmbH & Co. KG",            "is_nr": True},
    990_000_000_014: {"name": "Toyota Motor Corporation",         "is_nr": True},
    990_000_000_015: {"name": "Intel Corporation",                "is_nr": True},
    990_000_000_016: {"name": "Dell Technologies Inc.",           "is_nr": True},
    990_000_000_017: {"name": "Apple Distribution Ireland Ltd",   "is_nr": True},
    # Услуги и цифра (ПО, роялти, консалтинг) — avg ~3 млн ₸ × 12 инвойсов/год
    990_000_000_018: {"name": "Microsoft Corporation",            "is_nr": True},
    990_000_000_019: {"name": "Oracle Corporation",               "is_nr": True},
    990_000_000_020: {"name": "SAP SE",                           "is_nr": True},
    990_000_000_021: {"name": "Amazon Web Services Inc.",         "is_nr": True},
    990_000_000_022: {"name": "JetBrains s.r.o.",                 "is_nr": True},
    990_000_000_023: {"name": "Global Telecom NV",                "is_nr": True},
    990_000_000_024: {"name": "3M Company",                       "is_nr": True},
    990_000_000_025: {"name": "Logitech International SA",        "is_nr": True},

    # ══════ ② ЗАВИСИМЫЕ ОТ ИМПОРТА — резиденты, kz < 0.7 ══════
    # Сборщики/заводы — avg ~18 млн ₸ × 800 инвойсов/год
    990_000_000_050: {"name": "АО «АлматыТехКомплекс»",          "is_nr": False},
    990_000_000_051: {"name": "ТОО «КазМашИмпорт»",              "is_nr": False},
    990_000_000_052: {"name": "ТОО «НурСултанПром»",             "is_nr": False},
    990_000_000_053: {"name": "АО «ШымкентМашСтрой»",            "is_nr": False},
    # Тендерные игроки (госзакупки/СК) — avg ~9.5 млн ₸ × 150 инвойсов/год
    990_000_000_054: {"name": "ТОО «ТехноДистрибуция»",          "is_nr": False},
    990_000_000_055: {"name": "АО «ИТ-Сервис Казахстан»",        "is_nr": False},
    990_000_000_056: {"name": "ТОО «АлматыТехника»",             "is_nr": False},
    990_000_000_057: {"name": "ТОО «СтройЭлектро»",              "is_nr": False},
    990_000_000_058: {"name": "ТОО «МедТехника KZ»",             "is_nr": False},
    # Пищепром и легпром — avg ~2.5 млн ₸ × 450 инвойсов/год
    990_000_000_059: {"name": "ТОО «АвтоЗапчасть Плюс»",        "is_nr": False},
    990_000_000_060: {"name": "ТОО «ПромКомплект»",              "is_nr": False},
    990_000_000_061: {"name": "ТОО «ДигиталПоставка»",           "is_nr": False},
    # Сервис и IT на зарубежном ПО — avg ~4.5 млн ₸ × 100 инвойсов/год
    990_000_000_062: {"name": "АО «КазЭлектроника»",             "is_nr": False},
    990_000_000_063: {"name": "ТОО «КомпьютерТрейд»",            "is_nr": False},
    990_000_000_064: {"name": "ТОО «ЭнергоТехСервис»",           "is_nr": False},
    990_000_000_065: {"name": "ТОО «АстанаЛогистик»",            "is_nr": False},

    # ══════ ③ ЧИСТЫЕ ОТЕЧЕСТВЕННЫЕ — kz ≈ 1.0 ══════
    # Добыча и первичка — avg ~15 млн ₸ × 1200 инвойсов/год
    990_000_000_080: {"name": "АО «КазУгольДобыча»",             "is_nr": False},
    990_000_000_081: {"name": "АО «ЗерноПродукт Казахстан»",     "is_nr": False},
    990_000_000_082: {"name": "ТОО «ТаразРудаМет»",              "is_nr": False},
    # Стройматериалы — avg ~4.5 млн ₸ × 600 инвойсов/год
    990_000_000_083: {"name": "ТОО «АлтынАмалСтрой»",            "is_nr": False},
    990_000_000_084: {"name": "АО «СтройМатериалКЗ»",            "is_nr": False},
    990_000_000_085: {"name": "ТОО «КирпичЗавод Жезказган»",     "is_nr": False},
    990_000_000_086: {"name": "ТОО «КазЦемент»",                 "is_nr": False},
    # АПК и продукты — avg ~1.8 млн ₸ × 400 инвойсов/год
    990_000_000_087: {"name": "АО «КазМясоПром»",                "is_nr": False},
    990_000_000_088: {"name": "ТОО «КарагандаМолоко»",           "is_nr": False},
    990_000_000_089: {"name": "АО «АрматурПром»",                "is_nr": False},
    990_000_000_090: {"name": "ТОО «АлмаАтаМука»",               "is_nr": False},
    990_000_000_091: {"name": "ТОО «КазПродМаркет»",             "is_nr": False},

    # ══════ ④ ВСТРЕЧНАЯ ТОРГОВЛЯ ══════
    # Группа A — промышленный холдинг (взаимозачёты)
    990_000_000_100: {"name": "ТОО «ПромХолдинг Инвест»",        "is_nr": False},
    990_000_000_101: {"name": "ТОО «ПромХолдинг Энергия»",       "is_nr": False},
    990_000_000_102: {"name": "ТОО «ПромХолдинг Сервис»",        "is_nr": False},
    990_000_000_103: {"name": "ТОО «ПромХолдинг Сбыт»",          "is_nr": False},
    # Группа B — торгово-закупочная сеть (опт → розница → сервис)
    990_000_000_110: {"name": "ТОО «АлтынТорг Опт»",             "is_nr": False},
    990_000_000_111: {"name": "ТОО «АлтынТорг Розница»",         "is_nr": False},
    990_000_000_112: {"name": "ТОО «АлтынТорг Логистика»",       "is_nr": False},
    # Группа C — «схемные» цепочки
    990_000_000_120: {"name": "ТОО «ТрейдКонсалт А»",            "is_nr": False},
    990_000_000_121: {"name": "ТОО «ТрейдКонсалт Б»",            "is_nr": False},
    990_000_000_122: {"name": "ТОО «ТрейдКонсалт В»",            "is_nr": False},
}

# ──────────────────────────────────────────────────────────────────────────────
# OSD CHAIN — точные компании из ТЗ (с реальными БИН)
# ──────────────────────────────────────────────────────────────────────────────
OSD_TIN = 130240013649

OSD_CATALOG: dict[int, dict] = {
    # Уровень +1 — заказчики OSD
    550101400231:  {"name": "АО «ЦЭФ»",                "is_nr": False},
    940540000128:  {"name": "Procter & Gamble KZ",     "is_nr": True},
    90140001556:   {"name": "НКОК (NCOC)",             "is_nr": False},
    970940000215:  {"name": "АО «Каспи Банк»",         "is_nr": False},
    41040002883:   {"name": "АО «Казахмыс»",           "is_nr": False},
    # Уровень -1 — поставщики OSD
    100000000001:  {"name": "ТОО «ОФИСЫ»",             "is_nr": False},
    100000000002:  {"name": "ТОО «Интернет»",          "is_nr": False},
    100000000003:  {"name": "ТОО «Магазин»",           "is_nr": False},
    100000000004:  {"name": "ТОО «ЦОД»",               "is_nr": False},
    100000000005:  {"name": "ИП Разработчик1",         "is_nr": False},
    100000000006:  {"name": "ИП Разработчик2",         "is_nr": False},
    100000000007:  {"name": "ИП Разработчик3",         "is_nr": False},
    100000000008:  {"name": "ТОО «МагазЭлектроники»",  "is_nr": False},
    100000000009:  {"name": "ТОО «ПодпискаГугл»",      "is_nr": False},
    100000000010:  {"name": "Online Service LLC",      "is_nr": True},
    100000000011:  {"name": "ТОО «Дистрибьютер»",      "is_nr": False},
    100000000012:  {"name": "ТОО «ОборудованиеПлюс»",  "is_nr": False},
    # Уровень -2 — поставщики поставщиков
    200000000001:  {"name": "ТОО «ЭнергоСбыт»",        "is_nr": False},
    200000000002:  {"name": "ТОО «Чистый Мир»",        "is_nr": False},
    200000000003:  {"name": "Security Global Ltd",     "is_nr": True},
    200000000004:  {"name": "ТОО «Лифт-Сервис»",       "is_nr": False},
    200000000005:  {"name": "ТОО «СтройМастер»",       "is_nr": False},
    200000000006:  {"name": "Global Telecom NV",       "is_nr": True},
    200000000007:  {"name": "ТОО «КазахТелесеть»",     "is_nr": False},
    200000000008:  {"name": "Cisco Systems Inc.",      "is_nr": True},
    200000000009:  {"name": "ТОО «Дата-Центр Плюс»",   "is_nr": False},
    200000000010:  {"name": "ТОО «СпецСвязь»",         "is_nr": False},
    200000000011:  {"name": "Paper Production China",  "is_nr": True},
    200000000012:  {"name": "ТОО «ОптТорг»",           "is_nr": False},
    200000000013:  {"name": "ТОО «Логистик-Групп»",    "is_nr": False},
    200000000014:  {"name": "Branded Pens Corp",       "is_nr": True},
    200000000015:  {"name": "ТОО «Складской Терминал»","is_nr": False},
    200000000016:  {"name": "Cooling Systems GmbH",    "is_nr": True},
    200000000017:  {"name": "ТОО «ЭнергоПром»",        "is_nr": False},
    200000000018:  {"name": "Intel Corporation",       "is_nr": True},
    200000000019:  {"name": "ТОО «Пожарная Безопасность»","is_nr": False},
    200000000020:  {"name": "ТОО «Айти-Сервис»",       "is_nr": False},
    200000000021:  {"name": "GitHub Inc.",             "is_nr": True},
    200000000022:  {"name": "ТОО «Компьютерный Мир»",  "is_nr": False},
    200000000023:  {"name": "Amazon Web Services",     "is_nr": True},
    200000000024:  {"name": "ТОО «Учебный Центр Айти»","is_nr": False},
    200000000025:  {"name": "JetBrains s.r.o.",        "is_nr": True},
    200000000026:  {"name": "ТОО «Таможенный Брокер»", "is_nr": False},
    200000000027:  {"name": "ТОО «Транс-Евразия»",     "is_nr": False},
    200000000028:  {"name": "Warehouse Solutions LLC", "is_nr": True},
    # Уровень -3
    300000000001:  {"name": "АО «Станция ГРЭС»",       "is_nr": False},
    300000000002:  {"name": "Siemens Energy",          "is_nr": True},
    300000000003:  {"name": "ТОО «РемонтСеть»",        "is_nr": False},
    300000000004:  {"name": "Schneider Electric",      "is_nr": True},
    300000000005:  {"name": "ТОО «Безопасный Ток»",    "is_nr": False},
    300000000006:  {"name": "ТОО «ХимПром»",           "is_nr": False},
    300000000007:  {"name": "Kärcher GmbH",            "is_nr": True},
    300000000008:  {"name": "ТОО «Спецодежда-КЗ»",     "is_nr": False},
    300000000009:  {"name": "3M Company",              "is_nr": True},
    300000000010:  {"name": "ТОО «Инвент-Склад»",      "is_nr": False},
    300000000011:  {"name": "ТОО «КабельЗавод»",       "is_nr": False},
    300000000012:  {"name": "Huawei Technologies",     "is_nr": True},
    300000000013:  {"name": "ТОО «Монтаж-Связь»",      "is_nr": False},
    300000000014:  {"name": "Nokia Networks",          "is_nr": True},
    300000000015:  {"name": "ТОО «МеталлоКонструкция»","is_nr": False},
    300000000016:  {"name": "Faber-Castell AG",        "is_nr": True},
    300000000017:  {"name": "ТОО «Бумага-Групп»",      "is_nr": False},
    300000000018:  {"name": "Erich Krause Finland",    "is_nr": True},
    300000000019:  {"name": "ТОО «Пластик-КЗ»",        "is_nr": False},
    300000000020:  {"name": "ТОО «Складской Комплекс»","is_nr": False},
    300000000021:  {"name": "ТОО «ТопЛиво»",           "is_nr": False},
    300000000022:  {"name": "Caterpillar Inc.",        "is_nr": True},
    300000000023:  {"name": "ТОО «ТехСервис»",         "is_nr": False},
    300000000024:  {"name": "APC by Schneider",        "is_nr": True},
    300000000025:  {"name": "ТОО «Монтаж-Энерго»",     "is_nr": False},
    300000000026:  {"name": "Apple Distribution",      "is_nr": True},
    300000000027:  {"name": "ТОО «Логистика-Плюс»",    "is_nr": False},
    300000000028:  {"name": "Dell Technologies",       "is_nr": True},
    300000000029:  {"name": "ТОО «Сертификат-Центр»",  "is_nr": False},
    300000000030:  {"name": "Logitech International",  "is_nr": True},
    300000000031:  {"name": "ТОО «Petrol Service»",    "is_nr": False},
    300000000032:  {"name": "Volvo Trucks Corp",       "is_nr": True},
    300000000033:  {"name": "ТОО «Шиномонтаж-Про»",   "is_nr": False},
    300000000034:  {"name": "Garmin Ltd.",             "is_nr": True},
    300000000035:  {"name": "ТОО «Страховка-Центр»",   "is_nr": False},
    # Вендоры дистрибьютера
    100000000013:  {"name": "ТОО вендор (NR)",         "is_nr": True},
    100000000014:  {"name": "ТОО вендор2 (NR)",        "is_nr": True},
    # OSD сам
    OSD_TIN:       {"name": "ТОО «ОСД»",               "is_nr": False},
}

# Объединённый каталог (для overlay имён в engine.py)
FULL_SYNTHETIC_CATALOG: dict[int, dict] = {**SYNTHETIC_CATALOG, **OSD_CATALOG}

# ──────────────────────────────────────────────────────────────────────────────
# Группы встречной торговли ④
# ──────────────────────────────────────────────────────────────────────────────
_CYCLE_GROUPS: list[list[int]] = [
    [990_000_000_100, 990_000_000_101, 990_000_000_102, 990_000_000_103],
    [990_000_000_110, 990_000_000_111, 990_000_000_112],
    [990_000_000_120, 990_000_000_121, 990_000_000_122],
]

_NR_TINS = [t for t, v in SYNTHETIC_CATALOG.items() if v["is_nr"]]
_DEP_TINS = [t for t, v in SYNTHETIC_CATALOG.items()
             if not v["is_nr"] and 990_000_000_050 <= t <= 990_000_000_069]
_CLEAN_TINS = [t for t, v in SYNTHETIC_CATALOG.items()
               if not v["is_nr"] and 990_000_000_080 <= t <= 990_000_000_095]

INVOICE_SEARCH = "invoice_search"
INVOICE_ADVANCED = "invoice_search_advanced"

# Имя БД-эталона для CREATE TABLE ... LIKE (тот же сервер, что MYSQL_SYNTHETIC_*).
_SAFE_IDENT = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _quote_db(name: str) -> str:
    s = name.strip()
    if not _SAFE_IDENT.match(s):
        raise ValueError(f"Недопустимое имя базы для SQL: {name!r}")
    return f"`{s}`"


def _invoice_tables_present(engine: Engine) -> set[str]:
    sql = text(
        f"""
        SELECT TABLE_NAME FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME IN ('{INVOICE_SEARCH}', '{INVOICE_ADVANCED}')
        """
    )
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(sql).fetchall()}


def _source_has_table(engine: Engine, source_db: str, table: str) -> bool:
    q = text(
        """
        SELECT COUNT(*) FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :tname
        """
    )
    with engine.connect() as conn:
        n = conn.execute(q, {"schema": source_db, "tname": table}).scalar()
    return bool(n)


def _bootstrap_invoice_tables_like(engine: Engine, source_db: str, missing: set[str]) -> None:
    sd = _quote_db(source_db)
    for tbl in sorted(missing):
        if not _source_has_table(engine, source_db, tbl):
            raise RuntimeError(
                f"В базе-эталоне {source_db!r} нет таблицы {tbl!r}. "
                "Проверьте MYSQL_SYNTHETIC_SCHEMA_SOURCE."
            )
        tq = _quote_db(tbl)
        ddl = text(f"CREATE TABLE {tq} LIKE {sd}.{tq}")
        with engine.begin() as conn:
            conn.execute(ddl)


COLS_SQL = text(
    """
    SELECT
        COLUMN_NAME,
        DATA_TYPE,
        COLUMN_TYPE,
        IS_NULLABLE,
        COLUMN_DEFAULT,
        EXTRA
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = :table_name
    ORDER BY ORDINAL_POSITION
    """
)
@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    column_type: str
    is_nullable: bool
    column_default: str | None
    extra: str

    @property
    def is_auto_increment(self) -> bool:
        return "auto_increment" in (self.extra or "").lower()

    @property
    def is_generated(self) -> bool:
        return "GENERATED" in (self.extra or "").upper()


def _load_columns(engine: Engine, table: str) -> list[ColumnInfo]:
    with engine.connect() as conn:
        rows = conn.execute(COLS_SQL, {"table_name": table}).mappings().all()
    return [
        ColumnInfo(
            name=str(r["COLUMN_NAME"]),
            data_type=str(r["DATA_TYPE"]),
            column_type=str(r["COLUMN_TYPE"]),
            is_nullable=r["IS_NULLABLE"] == "YES",
            column_default=r["COLUMN_DEFAULT"],
            extra=str(r["EXTRA"] or ""),
        )
        for r in rows
    ]


def _insertable_columns(cols: Sequence[ColumnInfo]) -> list[ColumnInfo]:
    return [c for c in cols if not c.is_generated]


def _format_tin(val: int, column_type: str) -> Any:
    ct = column_type.lower()
    if any(x in ct for x in ("bigint", "int", "mediumint", "smallint", "tinyint")):
        return int(val)
    return str(int(val))


def _random_price(rng: random.Random) -> float:
    # ~ сотни тысяч — единицы млн ₸ без НДС
    return round(min(999_999_999_999.99, max(1000.0, math.exp(rng.gauss(13.5, 1.6)))), 2)


def _random_turnover_calendar_year(rng: random.Random, year: int) -> datetime:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    span = (end - start).days
    d = start + timedelta(days=rng.randint(0, span))
    return datetime(d.year, d.month, d.day, rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59))


def _rolling_turnover_bounds(today: date | None = None) -> tuple[date, date]:
    """Инклюзивно: от (сегодня − 365 дней) до сегодня по календарным датам."""
    t = today or date.today()
    return t - timedelta(days=365), t


def _random_turnover_in_range(rng: random.Random, date_start: date, date_end: date) -> datetime:
    span = max(0, (date_end - date_start).days)
    d = date_start + timedelta(days=rng.randint(0, span))
    return datetime(d.year, d.month, d.day, rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59))


def _rnd_turnover(
    rng: random.Random,
    period_mode: str,
    calendar_year: int | None,
    date_start: date,
    date_end: date,
) -> datetime:
    if period_mode == "calendar_year":
        assert calendar_year is not None
        return _random_turnover_calendar_year(rng, calendar_year)
    return _random_turnover_in_range(rng, date_start, date_end)


# ──────────────────────────────────────────────────────────────────────────────
# PRE-COMPILED ROW BUILDER
# Вычисляем структуру колонок один раз, потом построение строки — цикл по
# числовым слотам без if/elif по именам. Ускоряет вставку в ~3-4 раза.
# ──────────────────────────────────────────────────────────────────────────────
_SLOT_INV_ID    = 0
_SLOT_SELL_INT  = 1   # seller_tin → int
_SLOT_SELL_STR  = 2   # seller_tin → str
_SLOT_CUST_INT  = 3
_SLOT_CUST_STR  = 4
_SLOT_AMOUNT    = 5
_SLOT_AMOUNT_TX = 6   # amount * 1.12
_SLOT_TURN_DT   = 7   # datetime
_SLOT_TURN_D    = 8   # .date()
_SLOT_TURN_T    = 9   # .time()
_SLOT_TURN_Y    = 10  # .year
_SLOT_IS_NR     = 11
_SLOT_NULL      = 12  # nullable → None
_SLOT_INT0      = 13  # NOT NULL int/float → 0
_SLOT_STR0      = 14  # NOT NULL str → ""
_SLOT_BYTES0    = 15  # NOT NULL bytes → b""
_SLOT_INV_NUM   = 16  # invoice_number → "SYN-{id}"

_SELLER_KEYS = frozenset(
    ("seller_tin", "seller_taxpayer_number", "seller_bin", "seller_iin", "seller_iin_bin")
)
_CUSTOMER_KEYS = frozenset(
    ("customer_tin", "customer_taxpayer_number", "customer_bin",
     "buyer_tin", "customer_iin", "buyer_iin")
)
_AMOUNT_KEYS = frozenset(
    ("total_price_without_tax", "total_price_wo_tax", "price_without_tax", "amount_without_tax")
)


def _compile_table_insert(
    cols: list[ColumnInfo],
    table: str,
) -> tuple[str, Any]:
    """Один раз разбирает структуру колонок и возвращает (INSERT SQL, row_builder).

    ``row_builder(inv_id, seller, customer, amount, turnover, is_nr) -> tuple``
    вызывается для каждой строки и работает в ~3-4 раза быстрее _row_dict_for_table.
    """
    slots: list[int] = []
    col_names: list[str] = []

    for c in cols:
        if c.is_generated:
            continue
        name = c.name
        dt = c.data_type.lower()
        ct = c.column_type.lower()
        is_int_ct = any(x in ct for x in ("bigint", "int", "mediumint", "smallint", "tinyint"))
        is_num_dt = dt in ("decimal", "numeric", "float", "double")
        is_sell = name in _SELLER_KEYS or (
            "seller" in name and ("tin" in name or "iin" in name)
        )
        is_cust = name in _CUSTOMER_KEYS or (
            ("customer" in name or "buyer" in name) and ("tin" in name or "iin" in name)
        )

        if name == "invoice_id":
            slot = _SLOT_INV_ID
        elif is_sell:
            slot = _SLOT_SELL_INT if is_int_ct else _SLOT_SELL_STR
        elif is_cust:
            slot = _SLOT_CUST_INT if is_int_ct else _SLOT_CUST_STR
        elif name == "is_seller_non_resident":
            slot = _SLOT_IS_NR
        elif name in _AMOUNT_KEYS or (
            "without_tax" in name and (is_int_ct or is_num_dt)
        ):
            slot = _SLOT_AMOUNT
        elif name == "total_price_with_tax" and is_num_dt:
            slot = _SLOT_AMOUNT_TX
        elif name == "turnover_date":
            slot = _SLOT_TURN_DT
        elif name in ("invoice_number", "num", "number") and c.is_nullable:
            slot = _SLOT_INV_NUM
        elif c.is_nullable:
            slot = _SLOT_NULL
        elif c.column_default is not None:
            continue  # MySQL подставит DEFAULT; не включаем в INSERT
        elif dt in ("date",):
            slot = _SLOT_TURN_D
        elif dt in ("datetime", "timestamp"):
            slot = _SLOT_TURN_DT
        elif dt == "time":
            slot = _SLOT_TURN_T
        elif dt == "year":
            slot = _SLOT_TURN_Y
        elif is_int_ct or dt == "bit" or is_num_dt:
            slot = _SLOT_INT0
        elif dt in ("varchar", "char", "text", "mediumtext", "longtext"):
            slot = _SLOT_STR0
        elif dt in ("binary", "varbinary", "blob"):
            slot = _SLOT_BYTES0
        else:
            slot = _SLOT_NULL

        slots.append(slot)
        col_names.append(name)

    ph = ",".join(["%s"] * len(col_names))
    col_sql = ",".join(f"`{c}`" for c in col_names)
    sql = f"INSERT INTO `{table}` ({col_sql}) VALUES ({ph})"

    # Замораживаем слоты в tuple — быстрее list для итерации
    _slots = tuple(slots)

    def build_row(
        inv_id: int,
        seller: int,
        customer: int,
        amount: float,
        turnover: datetime,
        is_nr: int,
    ) -> tuple:
        out: list = []
        for k in _slots:
            if k == _SLOT_INV_ID:    out.append(inv_id)
            elif k == _SLOT_SELL_INT: out.append(seller)
            elif k == _SLOT_SELL_STR: out.append(str(seller))
            elif k == _SLOT_CUST_INT: out.append(customer)
            elif k == _SLOT_CUST_STR: out.append(str(customer))
            elif k == _SLOT_AMOUNT:   out.append(amount)
            elif k == _SLOT_AMOUNT_TX: out.append(round(amount * 1.12, 2))
            elif k == _SLOT_TURN_DT:  out.append(turnover)
            elif k == _SLOT_TURN_D:   out.append(turnover.date())
            elif k == _SLOT_TURN_T:   out.append(turnover.time())
            elif k == _SLOT_TURN_Y:   out.append(turnover.year)
            elif k == _SLOT_IS_NR:    out.append(is_nr)
            elif k == _SLOT_NULL:     out.append(None)
            elif k == _SLOT_INT0:     out.append(0)
            elif k == _SLOT_STR0:     out.append("")
            elif k == _SLOT_BYTES0:   out.append(b"")
            elif k == _SLOT_INV_NUM:  out.append(f"SYN-{inv_id}")
            else:                     out.append(None)
        return tuple(out)

    return sql, build_row


# (seller_tin, customer_tin, amount, is_seller_non_resident)
InvoiceRow = tuple[int, int, float, int]


def _osd_chain_invoices() -> list[InvoiceRow]:
    """Все счёт-фактуры цепочки OSD (точно по ТЗ, без рандома)."""
    rows: list[InvoiceRow] = []
    # Уровень +1: ТОО ОСД → заказчики
    for cust, amt in [
        (550101400231, 45_000_000), (550101400231, 12_000_000),
        (940540000128, 35_000_000), (940540000128, 5_500_000),
        (90140001556,  180_000_000), (90140001556, 28_000_000),
        (970940000215, 60_000_000), (970940000215, 96_000_000),
        (41040002883,  42_000_000), (41040002883,  15_500_000),
    ]:
        rows.append((OSD_TIN, cust, float(amt), 0))
    # Уровень -1: поставщики → ТОО ОСД
    for seller, amt, is_nr in [
        (100000000001,   600_000, 0),
        (100000000002,    50_000, 0),
        (100000000003,    50_000, 0),
        (100000000004,   100_000, 0),
        (100000000005, 7_000_000, 0),
        (100000000006, 7_000_000, 0),
        (100000000007, 7_000_000, 0),
        (100000000008,   300_000, 0),
        (100000000009,   300_000, 0),
        (100000000010, 3_000_000, 1),
        (100000000011, 80_000_000, 0),
        (100000000012, 150_000_000, 0),
    ]:
        rows.append((seller, OSD_TIN, float(amt), is_nr))
    # Уровень -2: поставщики поставщиков
    level2: list[tuple[int, int, float, int]] = [
        (200000000001, 100000000001, 150_000, 0),
        (200000000002, 100000000001,  80_000, 0),
        (200000000003, 100000000001, 200_000, 1),
        (200000000004, 100000000001,  50_000, 0),
        (200000000005, 100000000001, 120_000, 0),
        (200000000006, 100000000002, 1_500_000, 1),
        (200000000007, 100000000002,   300_000, 0),
        (200000000008, 100000000002, 2_000_000, 1),
        (200000000009, 100000000002,   100_000, 0),
        (200000000010, 100000000002,    40_000, 0),
        (200000000011, 100000000003,   800_000, 1),
        (200000000012, 100000000003,   150_000, 0),
        (200000000013, 100000000003,    60_000, 0),
        (200000000014, 100000000003,   400_000, 1),
        (200000000015, 100000000003,    90_000, 0),
        (200000000016, 100000000004, 1_200_000, 1),
        (200000000017, 100000000004,   900_000, 0),
        (200000000018, 100000000004, 5_000_000, 1),
        (200000000019, 100000000004,    70_000, 0),
        (200000000020, 100000000004,   250_000, 0),
        (200000000021, 100000000005,    15_000, 1),
        (200000000022, 100000000005,   450_000, 0),
        (200000000023, 100000000005,   100_000, 1),
        (200000000024, 100000000005,    80_000, 0),
        (200000000025, 100000000005,    60_000, 1),
        (200000000021, 100000000006,    15_000, 1),
        (200000000022, 100000000006,   450_000, 0),
        (200000000023, 100000000006,   100_000, 1),
        (200000000021, 100000000007,    15_000, 1),
        (200000000022, 100000000007,   450_000, 0),
        (200000000025, 100000000007,    60_000, 1),
        (100000000013, 100000000011,  60_000_000, 1),
        (100000000014, 100000000011, 120_000_000, 1),
        (200000000026, 100000000011,   500_000, 0),
        (200000000027, 100000000011, 2_000_000, 0),
        (200000000028, 100000000011,   300_000, 1),
    ]
    rows.extend(level2)
    # Уровень -3
    level3: list[tuple[int, int, float, int]] = [
        (300000000001, 200000000001, 8_000_000, 0),
        (300000000002, 200000000001, 2_500_000, 1),
        (300000000003, 200000000001,   400_000, 0),
        (300000000004, 200000000001, 1_200_000, 1),
        (300000000005, 200000000001,   150_000, 0),
        (300000000006, 200000000002,   300_000, 0),
        (300000000007, 200000000002,   900_000, 1),
        (300000000008, 200000000002,   120_000, 0),
        (300000000009, 200000000002,   200_000, 1),
        (300000000010, 200000000002,    80_000, 0),
        (300000000011, 200000000007, 3_000_000, 0),
        (300000000012, 200000000007, 15_000_000, 1),
        (300000000013, 200000000007, 1_500_000, 0),
        (300000000014, 200000000007, 7_000_000, 1),
        (300000000015, 200000000007, 2_000_000, 0),
        (300000000016, 200000000012, 5_000_000, 1),
        (300000000017, 200000000012, 1_200_000, 0),
        (300000000018, 200000000012, 2_500_000, 1),
        (300000000019, 200000000012,   400_000, 0),
        (300000000020, 200000000012,   600_000, 0),
        (300000000021, 200000000017, 2_000_000, 0),
        (300000000022, 200000000017, 25_000_000, 1),
        (300000000023, 200000000017,   500_000, 0),
        (300000000024, 200000000017, 12_000_000, 1),
        (300000000025, 200000000017,   800_000, 0),
        (300000000026, 200000000022, 30_000_000, 1),
        (300000000027, 200000000022,   300_000, 0),
        (300000000028, 200000000022, 20_000_000, 1),
        (300000000029, 200000000022,   100_000, 0),
        (300000000030, 200000000022, 2_000_000, 1),
        (300000000031, 200000000027, 4_000_000, 0),
        (300000000032, 200000000027, 15_000_000, 1),
        (300000000033, 200000000027,   600_000, 0),
        (300000000034, 200000000027,   400_000, 1),
        (300000000035, 200000000027,   250_000, 0),
    ]
    rows.extend(level3)
    return rows


def _nr_archetype_invoices(
    rng: random.Random,
    end_buyers: list[int],
    period_mode: str,
    calendar_year: int | None,
    date_start: date,
    date_end: date,
) -> list[InvoiceRow]:
    """① Нерезиденты продают в Казахстан. По параметрам из ТЗ."""
    rows: list[InvoiceRow] = []
    # Распределение по категориям согласно ТЗ
    nr_profiles: list[tuple[int, int, float, float]] = [
        # (tin, count, avg_amount, sigma)
        (990_000_000_001, 200, 11_000_000, 0.6),  # Samsung — крупный
        (990_000_000_002, 200, 11_000_000, 0.5),  # Siemens
        (990_000_000_003, 180, 11_000_000, 0.7),  # Caterpillar
        (990_000_000_004, 160, 10_000_000, 0.6),  # GE
        (990_000_000_005, 140,  9_000_000, 0.5),  # ABB
        (990_000_000_006,  60,  8_000_000, 0.5),  # Huawei — средний
        (990_000_000_007,  55,  8_000_000, 0.5),  # Cisco
        (990_000_000_008,  50,  7_000_000, 0.4),  # Schneider
        (990_000_000_009,  45,  7_500_000, 0.5),  # Komatsu
        (990_000_000_010,  50,  6_000_000, 0.5),  # Volvo
        (990_000_000_011,  40,  6_000_000, 0.4),  # Nokia
        (990_000_000_012,  35,  6_500_000, 0.4),  # Ericsson
        (990_000_000_013,  45,  5_000_000, 0.5),  # Kärcher
        (990_000_000_014,  40,  7_000_000, 0.5),  # Toyota
        (990_000_000_015,  50,  5_000_000, 0.4),  # Intel
        (990_000_000_016,  45,  6_000_000, 0.5),  # Dell
        (990_000_000_017,  30,  6_000_000, 0.5),  # Apple
        (990_000_000_018,  15,  3_000_000, 0.5),  # Microsoft — услуги
        (990_000_000_019,  12,  3_000_000, 0.5),  # Oracle
        (990_000_000_020,  12,  2_500_000, 0.4),  # SAP
        (990_000_000_021,  10,  2_000_000, 0.5),  # AWS
        (990_000_000_022,  10,  1_500_000, 0.4),  # JetBrains
        (990_000_000_023,  12,  2_000_000, 0.5),  # Global Telecom
        (990_000_000_024,  10,  2_500_000, 0.4),  # 3M
        (990_000_000_025,  10,  1_500_000, 0.4),  # Logitech
    ]
    # DEP компании убраны из списка — их NR-снабжение контролируется
    # явно в _dep_sales_invoices, чтобы гарантировать kz в диапазоне 0.05–0.28.
    buyers_ext = end_buyers
    for tin, count, avg, sigma in nr_profiles:
        for _ in range(count):
            buyer = rng.choice(buyers_ext)
            while buyer == tin:
                buyer = rng.choice(buyers_ext)
            amount = round(
                min(999_999_999.0, max(500_000.0, avg * math.exp(rng.gauss(0, sigma)))), 2
            )
            t = _rnd_turnover(rng, period_mode, calendar_year, date_start, date_end)
            rows.append((tin, buyer, amount, 1))
    return rows


def _dep_sales_invoices(
    rng: random.Random,
    end_buyers: list[int],
    period_mode: str,
    calendar_year: int | None,
    date_start: date,
    date_end: date,
) -> list[InvoiceRow]:
    """② Зависимые от импорта — продажи (покупки от NR уже сделаны в _nr_archetype_invoices)."""
    rows: list[InvoiceRow] = []
    dep_profiles = [
        # (tin, sales_count, avg_sale)
        (990_000_000_050, 200, 18_000_000),  # Сборщики/заводы
        (990_000_000_051, 180, 18_000_000),
        (990_000_000_052, 160, 15_000_000),
        (990_000_000_053, 150, 14_000_000),
        (990_000_000_054, 120,  9_500_000),  # Тендерные игроки
        (990_000_000_055, 100,  9_000_000),
        (990_000_000_056, 110,  8_500_000),
        (990_000_000_057,  90,  8_000_000),
        (990_000_000_058,  80,  7_500_000),
        (990_000_000_059, 180,  2_500_000),  # Пищепром
        (990_000_000_060, 160,  2_500_000),
        (990_000_000_061, 140,  2_000_000),
        (990_000_000_062,  90,  4_500_000),  # Сервис/IT
        (990_000_000_063,  80,  4_000_000),
        (990_000_000_064,  85,  4_000_000),
        (990_000_000_065,  70,  3_500_000),
    ]
    # DEP-компаниям задаём контролируемый kz в диапазоне 0.05–0.28.
    # Стратегия: явно генерируем NR-снабжение (is_nr=1) и CLEAN-снабжение (is_nr=0),
    # откалиброванное так, чтобы w_clean / (w_clean + w_nr) = target_kz.
    clean_tin_list = list(_CLEAN_TINS)
    for tin, n_sales, avg in dep_profiles:
        target_kz = rng.uniform(0.05, 0.28)  # желаемый kz: немного, но больше 0

        # NR-снабжение: 5–10 инвойсов от случайных NR-поставщиков
        n_nr = rng.randint(5, 10)
        nr_unit = avg * rng.uniform(0.35, 0.75)  # каждый NR-инвойс ≈ 35–75% avg_sale
        total_nr_w = 0.0
        for _ in range(n_nr):
            nr_sup = rng.choice(_NR_TINS)
            amt = round(max(500_000.0, nr_unit * math.exp(rng.gauss(0, 0.35))), 2)
            rows.append((nr_sup, tin, amt, 1))
            total_nr_w += amt

        # CLEAN-снабжение: объём откалиброван под target_kz
        # w_clean = total_nr_w * target_kz / (1 - target_kz)
        clean_budget = total_nr_w * target_kz / (1.0 - target_kz)
        n_clean = rng.randint(3, 7)
        clean_unit = clean_budget / n_clean
        for _ in range(n_clean):
            supplier = rng.choice(clean_tin_list)
            amt = round(max(50_000.0, clean_unit * math.exp(rng.gauss(0, 0.35))), 2)
            rows.append((supplier, tin, amt, 0))

        # Продажи конечным покупателям
        for _ in range(n_sales):
            buyer = rng.choice(end_buyers)
            while buyer == tin:
                buyer = rng.choice(end_buyers)
            amount = round(
                min(999_999_999.0, max(100_000.0, avg * math.exp(rng.gauss(0, 0.5)))), 2
            )
            rows.append((tin, buyer, amount, 0))
    return rows


def _clean_invoices(
    rng: random.Random,
    end_buyers: list[int],
    period_mode: str,
    calendar_year: int | None,
    date_start: date,
    date_end: date,
) -> list[InvoiceRow]:
    """③ Чистые отечественные — только резидентные цепочки (kz ≈ 1.0)."""
    rows: list[InvoiceRow] = []
    clean_profiles = [
        (990_000_000_080, 600, 15_000_000),  # Добыча
        (990_000_000_081, 550, 14_000_000),
        (990_000_000_082, 500, 12_000_000),
        (990_000_000_083, 350,  4_500_000),  # Стройматериалы
        (990_000_000_084, 300,  4_500_000),
        (990_000_000_085, 280,  4_000_000),
        (990_000_000_086, 260,  3_500_000),
        (990_000_000_087, 250,  1_800_000),  # АПК
        (990_000_000_088, 220,  1_800_000),
        (990_000_000_089, 200,  1_500_000),
        (990_000_000_090, 180,  1_500_000),
        (990_000_000_091, 160,  1_200_000),
    ]
    all_clean = list(_CLEAN_TINS)
    nr_supplier_tins = _NR_TINS  # для редких «грязных» закупок у ~35% CLEAN-компаний

    # Двухуровневый DAG: первые 6 компаний — «поставщики сырья/стройматериалов» (tier-1),
    # следующие 6 — «переработчики / торговые дома» (tier-2). tier-2 покупает у tier-1.
    # Это гарантирует отсутствие циклов и группа ③ не попадает в ④.
    supplier_tier = all_clean[:6]   # 990000000080-085
    buyer_tier    = all_clean[6:]   # 990000000086-091

    for tin, n_sales, avg in clean_profiles:
        # Покупки ТОЛЬКО по направлению tier-1 → tier-2 (ацикличный DAG)
        # tier-1 (поставщики): покупают у end_buyers (листья — kz=1.0)
        # tier-2 (переработчики): покупают у tier-1 (kz тоже ≈1.0, без цикла)
        is_buyer_tier = tin in buyer_tier
        clean_suppliers = supplier_tier if is_buyer_tier else []
        n_buys = max(20, n_sales // 10) if is_buyer_tier else 0
        total_resident_spend = 0.0
        for _ in range(n_buys):
            supplier = rng.choice(clean_suppliers)
            amt = round(max(100_000.0, avg * 0.3 * math.exp(rng.gauss(0, 0.4))), 2)
            rows.append((supplier, tin, amt, 0))
            total_resident_spend += amt

        # Редкие NR-покупки только у tier-2 CLEAN-компаний (~35%), у которых есть
        # резидентные закупки (total_resident_spend > 0).
        # → kz = 0.992–0.999 (проходит порог 0.99, но не ровно 1.00)
        # tier-1 не загрязняем: у них нет резидентной базы → kz=1.0 как листовые узлы ✓
        if nr_supplier_tins and total_resident_spend > 0 and rng.random() < 0.50:
            n_nr_buys = rng.randint(1, 2)
            # Сумма всех NR-покупок = 0.1%–0.8% от общего резидентного объёма
            nr_budget = total_resident_spend * rng.uniform(0.001, 0.008)
            for _ in range(n_nr_buys):
                nr_sup = rng.choice(nr_supplier_tins)
                amt = round(max(50_000.0, nr_budget / n_nr_buys
                                * math.exp(rng.gauss(0, 0.3))), 2)
                rows.append((nr_sup, tin, amt, 1))

        # Продажи — конечным покупателям
        for _ in range(n_sales):
            buyer = rng.choice(end_buyers)
            while buyer == tin:
                buyer = rng.choice(end_buyers)
            amount = round(
                min(999_999_999.0, max(50_000.0, avg * math.exp(rng.gauss(0, 0.4)))), 2
            )
            rows.append((tin, buyer, amount, 0))
    return rows


def _cycle_invoices(
    rng: random.Random,
    period_mode: str,
    calendar_year: int | None,
    date_start: date,
    date_end: date,
) -> list[InvoiceRow]:
    """④ Встречная торговля — намеренные циклы (ограниченное количество)."""
    rows: list[InvoiceRow] = []
    counts = [40, 25, 20]  # инвойсов внутри каждой группы
    for group, n in zip(_CYCLE_GROUPS, counts):
        m = len(group)
        for _ in range(n):
            i = rng.randrange(m)
            j = (i + 1 + rng.randint(0, m - 2)) % m
            amount = round(rng.uniform(5_000_000, 50_000_000), 2)
            rows.append((group[i], group[j], amount, 0))
    return rows


def _random_acyclic_invoices(
    count: int,
    rng: random.Random,
    tier_size: int,
    period_mode: str,
    calendar_year: int | None,
    date_start: date,
    date_end: date,
) -> tuple[list[InvoiceRow], list[int]]:
    """Случайная ацикличная сеть: tier1 (продавцы) → tier2 (покупатели).

    Никогда не создаёт ребро назад (tier2 → tier1), поэтому SCCs не возникают.
    Возвращает (invoice_rows, all_tins_list).
    """
    rows: list[InvoiceRow] = []
    # Генерируем tier_size + tier_size BIN'ов
    n = tier_size
    sellers: list[int] = []
    buyers: list[int] = []
    seen: set[int] = set(SYNTHETIC_CATALOG.keys()) | set(OSD_CATALOG.keys())
    seen.add(OSD_TIN)

    # BIN'ы продавцов — начало диапазона
    while len(sellers) < n:
        t = rng.randint(200_000_000_000, 599_999_999_999)
        if t not in seen:
            sellers.append(t)
            seen.add(t)

    # BIN'ы покупателей — другой диапазон
    while len(buyers) < n:
        t = rng.randint(600_000_000_000, 899_999_999_999)
        if t not in seen:
            buyers.append(t)
            seen.add(t)

    for _ in range(count):
        seller = rng.choice(sellers)
        buyer = rng.choice(buyers)
        amount = round(min(50_000_000.0, max(50_000.0, math.exp(rng.gauss(13.0, 1.4)))), 2)
        rows.append((seller, buyer, amount, 0))

    return rows, sellers + buyers


def _filler_for_type(data_type: str, column_type: str, turnover: datetime) -> Any:
    dt = data_type.lower()
    if dt in ("bigint", "int", "integer", "mediumint", "smallint", "tinyint"):
        return 0
    if dt in ("decimal", "numeric", "float", "double"):
        return 0
    if dt == "bit":
        return 0
    if dt in ("varchar", "char", "text", "mediumtext", "longtext"):
        return ""
    if dt in ("binary", "varbinary", "blob"):
        return b""
    if dt == "json":
        return None
    if dt in ("date",):
        return turnover.date()
    if dt in ("datetime", "timestamp"):
        return turnover
    if dt == "time":
        return turnover.time()
    if dt == "year":
        return turnover.year
    return None


def _row_dict_for_table(
    cols: Sequence[ColumnInfo],
    ctx: Mapping[str, Any],
    rng: random.Random,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    invoice_id = ctx["invoice_id"]
    seller = ctx["seller_tin"]
    customer = ctx["customer_tin"]
    amount = ctx["total_price_without_tax"]
    turnover: datetime = ctx["turnover_date"]
    is_nr = ctx.get("is_seller_non_resident", 0)

    seller_keys = (
        "seller_tin",
        "seller_taxpayer_number",
        "seller_bin",
        "seller_iin",
        "seller_iin_bin",
    )
    customer_keys = (
        "customer_tin",
        "customer_taxpayer_number",
        "customer_bin",
        "buyer_tin",
        "customer_iin",
        "buyer_iin",
    )

    for c in cols:
        name = c.name
        if c.is_generated:
            continue
        dt = c.data_type.lower()
        ct = c.column_type.lower()

        if name == "invoice_id":
            out[name] = int(invoice_id)
            continue
        if name in seller_keys or (
            "seller" in name.lower() and ("tin" in name.lower() or "iin" in name.lower())
        ):
            out[name] = _format_tin(seller, c.column_type)
            continue
        if name in customer_keys or (
            ("customer" in name.lower() or "buyer" in name.lower())
            and ("tin" in name.lower() or "iin" in name.lower())
        ):
            out[name] = _format_tin(customer, c.column_type)
            continue
        if name == "is_seller_non_resident":
            out[name] = is_nr
            continue
        if name in (
            "total_price_without_tax",
            "total_price_wo_tax",
            "price_without_tax",
            "amount_without_tax",
        ):
            out[name] = amount
            continue
        if "without_tax" in name.lower() and any(x in dt for x in ("decimal", "double", "float", "int")):
            out[name] = amount
            continue
        if name in ("total_price_with_tax",) and any(x in dt for x in ("decimal", "double", "float")):
            out[name] = round(amount * 1.12, 2)
            continue
        if name == "turnover_date":
            out[name] = turnover
            continue

        if c.is_nullable:
            if name in ("invoice_number", "num", "number") and rng.random() < 0.5:
                out[name] = f"SYN-{invoice_id}"
                continue
            out[name] = None
            continue

        if c.column_default is not None:
            # Сервер подставит DEFAULT при явном NULL нельзя для NOT NULL без default —
            # здесь default в метаданных есть (CURRENT_TIMESTAMP и т.д.): не включаем в INSERT?
            # лучше не опускать: для NOT NULL + DEFAULT в MySQL можно не передавать колонку.
            # Такие колонки пропускаем в keys — см. ниже сборку tuple
            continue

        val = _filler_for_type(c.data_type, c.column_type, turnover)
        out[name] = 0 if val is None and "int" in dt else ("" if val is None else val)

    return out


def _ordered_insert_parts(
    cols: Sequence[ColumnInfo],
    row: dict[str, Any],
) -> tuple[list[str], tuple[Any, ...]]:
    names: list[str] = []
    values: list[Any] = []
    insertable = {c.name for c in cols if not c.is_generated}
    for c in cols:
        if c.name not in insertable:
            continue
        if c.is_generated:
            continue
        if c.name not in row and c.column_default is not None:
            continue
        if c.name not in row:
            if c.is_nullable:
                names.append(c.name)
                values.append(None)
            else:
                raise RuntimeError(
                    f"Нет значения для обязательной колонки {c.name} и нет DEFAULT — "
                    "уточните схему или расширите synthetic_esf._row_dict_for_table."
                )
            continue
        names.append(c.name)
        values.append(row[c.name])
    return names, tuple(values)


def _ensure_invoice_tables_exist(engine: Engine) -> None:
    """Создаёт пустые invoice_search / invoice_search_advanced из эталона, если задан env."""
    need = {INVOICE_SEARCH, INVOICE_ADVANCED}
    found = _invoice_tables_present(engine)
    if found == need:
        return

    missing = need - found
    source = os.getenv("MYSQL_SYNTHETIC_SCHEMA_SOURCE", "").strip()
    if not source:
        raise RuntimeError(
            "В MYSQL_SYNTHETIC_DATABASE не хватает таблиц "
            f"{sorted(missing)}. Укажите MYSQL_SYNTHETIC_SCHEMA_SOURCE — имя боевой БД "
            "на этом же сервере (например esf-ver), откуда скопировать структуру через "
            "CREATE TABLE … LIKE; либо залейте DDL вручную (mysqldump --no-data)."
        )

    with engine.connect() as conn:
        target = conn.execute(text("SELECT DATABASE()")).scalar()
    if not target:
        raise RuntimeError("Подключение без базы: проверьте MYSQL_SYNTHETIC_DATABASE.")
    if source == target:
        raise RuntimeError(
            "MYSQL_SYNTHETIC_SCHEMA_SOURCE не может совпадать с именем целевой БД."
        )

    _bootstrap_invoice_tables_like(engine, source, missing)

    found2 = _invoice_tables_present(engine)
    if found2 != need:
        raise RuntimeError(
            "После копирования структуры таблицы всё ещё неполные: "
            f"ожидали {sorted(need)}, есть {sorted(found2)}."
        )


def truncate_synthetic_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        conn.execute(text(f"TRUNCATE TABLE `{INVOICE_ADVANCED}`"))
        conn.execute(text(f"TRUNCATE TABLE `{INVOICE_SEARCH}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def _log_progress(done: int, total: int, t0: float) -> None:
    elapsed = time.perf_counter() - t0
    pct = 100.0 * done / total if total else 0.0
    rate = done / elapsed if elapsed > 0 else 0.0
    left = total - done
    eta = left / rate if rate > 0 else 0.0
    print(
        f"[progress] {done:,} / {total:,} документов ({pct:.1f}%) | "
        f"время {elapsed:.1f} с | {rate:,.0f} док/с | осталось ~{eta:.0f} с",
        flush=True,
    )


def _gen_turnovers_bulk(
    rng: random.Random,
    n: int,
    period_mode: str,
    calendar_year: int | None,
    date_start: date,
    date_end: date,
) -> list[datetime]:
    """Генерирует n дат одним проходом без повторного вычисления span."""
    span = max(0, (date_end - date_start).days)
    ri = rng.randint
    if period_mode == "calendar_year":
        assert calendar_year is not None
        s = date(calendar_year, 1, 1)
        result = []
        for _ in range(n):
            d = s + timedelta(days=ri(0, span))
            result.append(datetime(d.year, d.month, d.day, ri(0, 23), ri(0, 59), ri(0, 59)))
    else:
        result = []
        for _ in range(n):
            d = date_start + timedelta(days=ri(0, span))
            result.append(datetime(d.year, d.month, d.day, ri(0, 23), ri(0, 59), ri(0, 59)))
    return result


def _build_all_rows(
    invoices: list[InvoiceRow],
    h_builder: Any,
    d_builder: Any,
    rng: random.Random,
    invoice_id_start: int,
    period_mode: str,
    calendar_year: int | None,
    date_start: date,
    date_end: date,
) -> tuple[list[tuple], list[tuple]]:
    """Строит все строки для обеих таблиц одним Python-проходом.

    Отделяем построение строк от сетевых вызовов — позволяет потом
    вставлять обе таблицы параллельно.
    """
    n = len(invoices)
    turnovers = _gen_turnovers_bulk(rng, n, period_mode, calendar_year, date_start, date_end)
    h_rows: list[tuple] = []
    d_rows: list[tuple] = []
    inv_id = invoice_id_start
    for (seller, customer, amount, is_nr), t in zip(invoices, turnovers):
        h_rows.append(h_builder(inv_id, seller, customer, amount, t, is_nr))
        d_rows.append(d_builder(inv_id, seller, customer, amount, t, is_nr))
        inv_id += 1
    return h_rows, d_rows


def _insert_worker(
    engine: Any,
    sql: str,
    all_rows: list[tuple],
    batch_size: int,
    exc_holder: list,
    progress_cb: Any | None = None,
) -> None:
    """Воркер-поток: вставляет all_rows в одну таблицу батчами."""
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        for i in range(0, len(all_rows), batch_size):
            chunk = all_rows[i: i + batch_size]
            cur.executemany(sql, chunk)
            raw.commit()
            if progress_cb is not None:
                progress_cb(len(chunk))
    except Exception as e:  # noqa: BLE001
        exc_holder.append(e)
    finally:
        try:
            raw.close()
        except Exception:
            pass


def _parallel_insert(
    engine: Any,
    h_sql: str,
    d_sql: str,
    h_rows: list[tuple],
    d_rows: list[tuple],
    batch_size: int,
    *,
    total_documents: int,
    progress_every: int,
    t0: float,
) -> None:
    """Вставляет invoice_search и invoice_search_advanced параллельно — двумя потоками.

    Учёт прогресса: сумма вставленных строк по обеим таблицам / 2 ≈ число учётных документов
    (пока оба потока идут, оценка может слегка отставать от факта).
    """
    exc_h: list = []
    exc_d: list = []
    prog_lock = threading.Lock()
    row_sum = 0
    last_logged_docs = 0

    def _on_batch(n: int) -> None:
        nonlocal row_sum, last_logged_docs
        if progress_every <= 0:
            return
        with prog_lock:
            row_sum += n
            done_docs = row_sum // 2
            if done_docs - last_logged_docs >= progress_every:
                _log_progress(min(done_docs, total_documents), total_documents, t0)
                last_logged_docs = done_docs

    t_h = threading.Thread(
        target=_insert_worker,
        args=(engine, h_sql, h_rows, batch_size, exc_h, _on_batch),
    )
    t_d = threading.Thread(
        target=_insert_worker,
        args=(engine, d_sql, d_rows, batch_size, exc_d, _on_batch),
    )
    t_h.start()
    t_d.start()
    t_h.join()
    t_d.join()
    if exc_h:
        raise RuntimeError(f"Ошибка при вставке {INVOICE_SEARCH}: {exc_h[0]}") from exc_h[0]
    if exc_d:
        raise RuntimeError(f"Ошибка при вставке {INVOICE_ADVANCED}: {exc_d[0]}") from exc_d[0]


def generate_synthetic_esf(
    *,
    engine: Engine,
    count: int,
    calendar_year: int | None,
    invoice_id_start: int,
    seed: int,
    tin_pool_size: int,
    batch_size: int,
    truncate: bool,
    progress_every: int = 10_000,
) -> dict[str, Any]:
    """Генерирует структурированные ЭСФ с 4 архетипами + цепочка OSD из ТЗ.

    Архетипы:
      ① NR-импортёры (25 именных компаний, ~2800 инвойсов по уровням из ТЗ)
      ② Зависимые от импорта (16 резидентов, kz < 0.7)
      ③ Чистые отечественные (12 резидентов, kz ≈ 1.0)
      ④ Встречная торговля (3 цикличные группы, ограниченный объём)
      OSD-chain (~150 инвойсов точно по ТЗ)
      random acyclic (DAG seller-tier → buyer-tier, нет случайных SCC)
    """
    if count < 1:
        raise ValueError("count >= 1")
    if progress_every < 0:
        raise ValueError("progress_every must be >= 0 (0 отключает отчёт).")

    rng = random.Random(seed)

    _ensure_invoice_tables_exist(engine)

    if calendar_year is not None:
        date_start = date(calendar_year, 1, 1)
        date_end = date(calendar_year, 12, 31)
        period_mode = "calendar_year"
    else:
        date_start, date_end = _rolling_turnover_bounds()
        period_mode = "rolling_365d"

    h_cols = _load_columns(engine, INVOICE_SEARCH)
    d_cols = _load_columns(engine, INVOICE_ADVANCED)
    hi = _insertable_columns(h_cols)
    di = _insertable_columns(d_cols)
    h_sql, h_builder = _compile_table_insert(hi, INVOICE_SEARCH)
    d_sql, d_builder = _compile_table_insert(di, INVOICE_ADVANCED)

    if truncate:
        truncate_synthetic_tables(engine)

    # ── Сборка структурных инвойсов ──────────────────────────────────────────
    osd_rows = _osd_chain_invoices()

    # Конечные покупатели для архетипов ① ② ③ — случайные BIN из tier2
    _, end_buyers = _random_acyclic_invoices(
        0, rng, max(tin_pool_size, 500), period_mode, calendar_year, date_start, date_end
    )
    end_buyers_buyers = end_buyers[len(end_buyers) // 2:]  # только «покупательский» tier

    nr_rows = _nr_archetype_invoices(rng, end_buyers_buyers, period_mode, calendar_year, date_start, date_end)
    dep_rows = _dep_sales_invoices(rng, end_buyers_buyers, period_mode, calendar_year, date_start, date_end)
    clean_rows = _clean_invoices(rng, end_buyers_buyers, period_mode, calendar_year, date_start, date_end)
    cycle_rows = _cycle_invoices(rng, period_mode, calendar_year, date_start, date_end)

    structured_count = len(osd_rows) + len(nr_rows) + len(dep_rows) + len(clean_rows) + len(cycle_rows)
    random_count = max(0, count - structured_count)
    random_rows, _ = _random_acyclic_invoices(
        random_count, rng, max(tin_pool_size, 500),
        period_mode, calendar_year, date_start, date_end,
    )

    all_invoices = osd_rows + nr_rows + dep_rows + clean_rows + cycle_rows + random_rows
    rng.shuffle(all_invoices)
    total = len(all_invoices)

    if progress_every > 0:
        print(
            f"[info] Всего инвойсов: {total:,}  "
            f"(OSD:{len(osd_rows)}, ①NR:{len(nr_rows)}, ②DEP:{len(dep_rows)}, "
            f"③CLEAN:{len(clean_rows)}, ④CYCLE:{len(cycle_rows)}, random:{len(random_rows)})  "
            f"батч:{batch_size:,}  отчёт каждые:{progress_every:,}",
            flush=True,
        )

    t0 = time.perf_counter()

    if progress_every > 0:
        print("[info] Строю строки в памяти…", flush=True)

    h_rows, d_rows = _build_all_rows(
        all_invoices, h_builder, d_builder, rng,
        invoice_id_start, period_mode, calendar_year, date_start, date_end,
    )
    inserted = len(h_rows)

    if progress_every > 0:
        build_t = time.perf_counter() - t0
        print(f"[info] Построено за {build_t:.1f} с. Вставляю в MySQL (2 таблицы параллельно)…", flush=True)

    _parallel_insert(
        engine,
        h_sql,
        d_sql,
        h_rows,
        d_rows,
        batch_size,
        total_documents=inserted,
        progress_every=progress_every,
        t0=t0,
    )

    if progress_every > 0:
        _log_progress(inserted, total, t0)

    elapsed = round(time.perf_counter() - t0, 2)
    return {
        "inserted_documents": inserted,
        "period_mode": period_mode,
        "turnover_date_from": date_start.isoformat(),
        "turnover_date_to": date_end.isoformat(),
        "calendar_year": calendar_year,
        "invoice_id_start": invoice_id_start,
        "elapsed_seconds": elapsed,
        "seed": seed,
        "breakdown": {
            "osd_chain": len(osd_rows),
            "nr_importers": len(nr_rows),
            "import_dependents": len(dep_rows),
            "clean_domestic": len(clean_rows),
            "cycle_trade": len(cycle_rows),
            "random_acyclic": len(random_rows),
        },
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Генерация синтетических ЭСФ в MYSQL_SYNTHETIC_* БД.")
    p.add_argument("--count", type=int, default=300_000, help="Число учётных документов (1:1 две таблицы).")
    p.add_argument(
        "--year",
        type=int,
        default=None,
        metavar="YYYY",
        help=(
            "Календарный год turnover_date (1 янв — 31 дек). "
            "Без этого флага — скользящий период: сегодня−365 дней … сегодня включительно."
        ),
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--invoice-id-start", type=int, default=1)
    p.add_argument(
        "--tin-pool-size", type=int, default=2_000,
        help="Размер пула случайных BIN'ов для tier-продавцов и tier-покупателей.",
    )
    p.add_argument("--batch-size", type=int, default=5_000)
    p.add_argument("--truncate", action="store_true", help="Очистить обе таблицы перед вставкой.")
    p.add_argument(
        "--progress-every",
        type=int,
        default=10_000,
        metavar="N",
        help=(
            "Печатать [progress] каждые N учётных документов во время вставки в MySQL "
            "(0 — только старт/финиш; по умолчанию во время INSERT в обе таблицы)."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _root = Path(__file__).resolve().parents[4]
    load_dotenv(_root / ".env")
    load_dotenv()
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    url = build_synthetic_connection_url()
    engine = create_engine(url, pool_pre_ping=True)
    try:
        summary = generate_synthetic_esf(
            engine=engine,
            count=args.count,
            calendar_year=args.year,
            invoice_id_start=args.invoice_id_start,
            seed=args.seed,
            tin_pool_size=args.tin_pool_size,
            batch_size=args.batch_size,
            truncate=args.truncate,
            progress_every=args.progress_every,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("[OK]", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
