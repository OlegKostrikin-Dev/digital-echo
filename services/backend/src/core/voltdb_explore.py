"""digital-echo-core: разведка схемы VoltDB.

Скрипт делает 4 вещи:
  1. Проверяет, что подключение к VoltDB работает.
  2. Печатает список ВСЕХ таблиц.
  3. Для интересующих таблиц (PROFILE, TAX_ORGANIZATION, TAXPAYER, ENTERPRISE_LINK,
     TAXPAYER_MARK, TAXPAYER_VAT) показывает колонки и примеры строк.
  4. Ищет колонки, которые могут содержать признак резидентности
     (по именам: resident, country, citizenship и т.п.).

Запуск:
    docker compose run --rm echo-engine python voltdb_explore.py

Перед запуском заполните VOLTDB_HOSTS, VOLTDB_USER, VOLTDB_PASSWORD в .env.
"""

import sys
from typing import Iterable

import pandas as pd

from .voltdb_client import VoltDBClient, VoltDBConfigError


# Таблицы, перечисленные архитектором как кандидаты для справочника компаний
TARGET_TABLES = [
    "PROFILE",
    "TAX_ORGANIZATION",
    "TAXPAYER",
    "ENTERPRISE_LINK",
    "TAXPAYER_MARK",
    "TAXPAYER_VAT",
    "TAXPAYER_ADDRESS",
    "BUSINESS_USER",
]

# Признаки, по которым может определяться резидентность/принадлежность к стране
RESIDENCY_HINTS = [
    "resident",
    "non_resident",
    "country",
    "citizenship",
    "is_foreign",
    "kz",
    "kazakhstan",
    "tin",
    "bin",
    "iin",
]


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_df(df: pd.DataFrame, max_rows: int = 50, max_cols: int = 20) -> None:
    if df.empty:
        print("(пусто)")
        return
    with pd.option_context(
        "display.max_rows", max_rows,
        "display.max_columns", max_cols,
        "display.width", 200,
        "display.max_colwidth", 80,
    ):
        print(df.to_string(index=False))


def find_residency_columns(columns_df: pd.DataFrame) -> pd.DataFrame:
    """Ищет в каталоге колонок поля, которые похожи на признак резидентности."""
    if columns_df.empty or "COLUMN_NAME" not in columns_df.columns:
        return pd.DataFrame()
    name_lower = columns_df["COLUMN_NAME"].astype(str).str.lower()
    mask = pd.Series([False] * len(columns_df))
    for hint in RESIDENCY_HINTS:
        mask = mask | name_lower.str.contains(hint, regex=False, na=False)
    return columns_df[mask].copy()


def explore_table(volt: VoltDBClient, table: str, sample_rows: int = 3) -> None:
    section(f"ТАБЛИЦА: {table}")
    cols = volt.list_columns(table_name=table)
    if cols.empty:
        print(f"(таблица {table} в каталоге не найдена)")
        return

    print(f"Колонок: {len(cols)}")
    show_cols = [c for c in ("COLUMN_NAME", "TYPE_NAME", "COLUMN_SIZE", "IS_NULLABLE", "REMARKS")
                 if c in cols.columns]
    print_df(cols[show_cols] if show_cols else cols, max_rows=200)

    # Попытаемся достать примеры строк
    try:
        sample = volt.query(f"SELECT * FROM {table} LIMIT {sample_rows}")
        print(f"\nПримеры строк (LIMIT {sample_rows}):")
        print_df(sample)

        # Кол-во строк
        cnt = volt.query(f"SELECT COUNT(*) AS rows_count FROM {table}")
        if not cnt.empty:
            print(f"\nИтого строк в {table}: {int(cnt.iloc[0, 0]):,}")
    except Exception as exc:
        print(f"[WARN] SELECT/COUNT по {table} не выполнился: {exc}")


def main(targets: Iterable[str] = TARGET_TABLES) -> int:
    try:
        volt = VoltDBClient.from_env()
    except VoltDBConfigError as exc:
        print(f"[ERROR] {exc}")
        print("\nЗаполните в .env:")
        print("  VOLTDB_HOSTS=host1,host2     # клиентские адреса VoltDB-кластера")
        print("  VOLTDB_PORT=21212            # порт по умолчанию")
        print("  VOLTDB_USER=...              # если включена аутентификация")
        print("  VOLTDB_PASSWORD=...")
        return 1

    print(f"[INFO] Подключение к VoltDB: hosts={volt._hosts}, port={volt._port}")

    try:
        volt.connect()
    except ConnectionError as exc:
        print(f"[ERROR] {exc}")
        print("\nПроверьте:")
        print("  1. Хост и порт VoltDB достижимы из контейнера (host.docker.internal или IP)")
        print("  2. У пользователя есть право на @SystemCatalog/@AdHoc")
        return 2

    try:
        # 1. Список ВСЕХ таблиц
        section("ВСЕ ТАБЛИЦЫ В VOLTDB")
        all_tables = volt.list_tables()
        if all_tables.empty:
            print("(каталог пуст или нет доступа к @SystemCatalog)")
            return 3

        cols_to_show = [c for c in ("TABLE_SCHEM", "TABLE_NAME", "TABLE_TYPE", "REMARKS")
                        if c in all_tables.columns]
        print_df(all_tables[cols_to_show] if cols_to_show else all_tables, max_rows=500)
        print(f"\nВсего таблиц: {len(all_tables)}")

        # 2. Поиск колонок с признаками резидентности по ВСЕЙ схеме
        section("ПОТЕНЦИАЛЬНЫЕ КОЛОНКИ С ПРИЗНАКОМ РЕЗИДЕНТНОСТИ / БИН")
        all_cols = volt.list_columns()
        candidates = find_residency_columns(all_cols)
        if candidates.empty:
            print("Колонок с подходящими именами не найдено.")
        else:
            show = [c for c in ("TABLE_NAME", "COLUMN_NAME", "TYPE_NAME", "REMARKS")
                    if c in candidates.columns]
            print_df(candidates[show] if show else candidates, max_rows=200)

        # 3. Детально по таблицам-кандидатам
        for tbl in targets:
            explore_table(volt, tbl)

        return 0

    except Exception as exc:
        print(f"[ERROR] Непредвиденная ошибка: {exc}")
        import traceback
        traceback.print_exc()
        return 4
    finally:
        volt.close()


if __name__ == "__main__":
    sys.exit(main())
