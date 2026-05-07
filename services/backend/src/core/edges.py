"""digital-echo-core: выгрузка агрегированных рёбер графа B2B-транзакций."""

import os
import sys
from datetime import date, timedelta
from urllib.parse import quote_plus

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


# SQL: агрегируем транзакции в рёбра графа (source -> target)
EDGES_QUERY = text(
    """
    SELECT
        h.seller_tin                        AS source,
        h.customer_tin                      AS target,
        SUM(d.total_price_without_tax)      AS weight,
        COUNT(DISTINCT h.invoice_id)        AS invoice_count
    FROM invoice_search           AS h
    INNER JOIN invoice_search_advanced AS d
            ON d.invoice_id = h.invoice_id
    WHERE d.turnover_date >= :date_from
      AND d.turnover_date <  :date_to
      AND h.seller_tin   IS NOT NULL
      AND h.customer_tin IS NOT NULL
      AND h.seller_tin <> ''
      AND h.customer_tin <> ''
    GROUP BY h.seller_tin, h.customer_tin
    """
)


# SQL: атрибуты узлов (резидент/нерезидент) — собираются из всех ЭСФ,
# где идентификатор узла — seller_tin в шапке. Если хотя бы в одном документе
# он помечен как нерезидент — считаем нерезидентом (консервативно).
NODE_ATTRS_QUERY = text(
    """
    SELECT
        h.seller_tin                              AS tin,
        MAX(COALESCE(h.is_seller_non_resident, 0)) AS is_non_resident,
        COUNT(DISTINCT h.invoice_id)              AS sale_invoices
    FROM invoice_search AS h
    INNER JOIN invoice_search_advanced AS d
            ON d.invoice_id = h.invoice_id
    WHERE d.turnover_date >= :date_from
      AND d.turnover_date <  :date_to
      AND h.seller_tin IS NOT NULL
      AND h.seller_tin <> ''
    GROUP BY h.seller_tin
    """
)


def build_connection_url() -> str:
    """Сборка URL подключения к боевой MySQL из MYSQL_*."""
    host = os.getenv("MYSQL_HOST")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD")
    database = os.getenv("MYSQL_DATABASE")

    if not all([host, user, password, database]):
        raise RuntimeError("Не заданы обязательные переменные окружения MySQL.")

    # quote_plus — на случай спецсимволов в пароле/имени БД (например, '$', '-')
    return (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}?charset=utf8mb4"
    )


def build_synthetic_connection_url() -> str:
    """Отдельная демо-БД с синтетическими ЭСФ (`esf_synthetic_demo` и т.п.)."""
    host = os.getenv("MYSQL_SYNTHETIC_HOST") or os.getenv("MYSQL_HOST")
    port = os.getenv("MYSQL_SYNTHETIC_PORT") or os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_SYNTHETIC_USER")
    password = os.getenv("MYSQL_SYNTHETIC_PASSWORD")
    database = os.getenv("MYSQL_SYNTHETIC_DATABASE")

    if not all([host, user, password, database]):
        raise RuntimeError(
            "Не заданы MYSQL_SYNTHETIC_HOST/USER/PASSWORD/DATABASE "
            "(или MYSQL_HOST как запасной для host)."
        )
    return (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}?charset=utf8mb4"
    )


def get_default_period(days: int = 30) -> tuple[date, date]:
    """Возвращает (date_from, date_to) — последние `days` дней до сегодня."""
    today = date.today()
    return today - timedelta(days=days), today


def main() -> int:
    load_dotenv()

    try:
        connection_url = build_connection_url()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 1

    date_from, date_to = get_default_period(days=30)
    print(f"[INFO] Период агрегации: {date_from} -> {date_to}")

    try:
        engine = create_engine(connection_url, pool_pre_ping=True)
        with engine.connect() as connection:
            df = pd.read_sql(
                EDGES_QUERY,
                connection,
                params={"date_from": date_from, "date_to": date_to},
            )

        print(f"[OK] Получено рёбер графа: {len(df)}")
        print("\n--- df.head() ---")
        print(df.head())
        print("\n--- df.info() ---")
        df.info()
        return 0

    except SQLAlchemyError as exc:
        print("[ERROR] Ошибка подключения или запроса к MySQL:")
        print(exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
