"""digital-echo-core: проверка B2B-активности конкретной компании по БИН/ТИН."""

import argparse
import sys
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from .edges import build_connection_url


# Исходящие транзакции: компания выступает ПРОДАВЦОМ
OUTGOING_QUERY = text(
    """
    SELECT
        h.customer_tin                      AS counterparty,
        SUM(d.total_price_without_tax)      AS weight,
        COUNT(DISTINCT h.invoice_id)        AS invoice_count,
        MIN(d.turnover_date)                AS first_date,
        MAX(d.turnover_date)                AS last_date
    FROM invoice_search           AS h
    INNER JOIN invoice_search_advanced AS d
            ON d.invoice_id = h.invoice_id
    WHERE h.seller_tin = :tin
      AND d.turnover_date >= :date_from
      AND d.turnover_date <  :date_to
      AND h.customer_tin IS NOT NULL
      AND h.customer_tin <> ''
    GROUP BY h.customer_tin
    ORDER BY weight DESC
    """
)


# Входящие транзакции: компания выступает ПОКУПАТЕЛЕМ
INCOMING_QUERY = text(
    """
    SELECT
        h.seller_tin                        AS counterparty,
        SUM(d.total_price_without_tax)      AS weight,
        COUNT(DISTINCT h.invoice_id)        AS invoice_count,
        MIN(d.turnover_date)                AS first_date,
        MAX(d.turnover_date)                AS last_date
    FROM invoice_search           AS h
    INNER JOIN invoice_search_advanced AS d
            ON d.invoice_id = h.invoice_id
    WHERE h.customer_tin = :tin
      AND d.turnover_date >= :date_from
      AND d.turnover_date <  :date_to
      AND h.seller_tin IS NOT NULL
      AND h.seller_tin <> ''
    GROUP BY h.seller_tin
    ORDER BY weight DESC
    """
)


def fmt_money(x: float) -> str:
    """Форматирование суммы с разделителями разрядов."""
    return f"{x:,.2f}".replace(",", " ")


def print_section(title: str, df: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    if df.empty:
        print("(нет данных)")
        return
    total_weight = df["weight"].sum()
    total_invoices = df["invoice_count"].sum()
    print(f"Контрагентов: {len(df)}")
    print(f"Сумма (без НДС): {fmt_money(total_weight)}")
    print(f"Документов всего: {int(total_invoices)}")
    print("\nТоп-10 контрагентов:")
    print(df.head(10).to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка B2B-активности компании")
    parser.add_argument("tin", help="БИН/ТИН компании, например 130240013649")
    parser.add_argument("--days", type=int, default=90, help="Глубина периода в днях (default: 90)")
    args = parser.parse_args()

    load_dotenv()

    try:
        connection_url = build_connection_url()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 1

    today = date.today()
    date_from = today - timedelta(days=args.days)
    date_to = today

    # Передаём БИН строкой — это безопасно для CHAR/VARCHAR-полей в MySQL
    params = {"tin": str(args.tin), "date_from": date_from, "date_to": date_to}

    print(f"[INFO] Компания: {args.tin}")
    print(f"[INFO] Период: {date_from} -> {date_to} ({args.days} дней)")

    try:
        engine = create_engine(connection_url, pool_pre_ping=True)
        with engine.connect() as connection:
            df_out = pd.read_sql(OUTGOING_QUERY, connection, params=params)
            df_in = pd.read_sql(INCOMING_QUERY, connection, params=params)

        print_section("ИСХОДЯЩИЕ (компания как ПРОДАВЕЦ)", df_out)
        print_section("ВХОДЯЩИЕ (компания как ПОКУПАТЕЛЬ)", df_in)

        sales = float(df_out["weight"].sum()) if not df_out.empty else 0.0
        purchases = float(df_in["weight"].sum()) if not df_in.empty else 0.0
        print("\n=== ИТОГО ===")
        print(f"Продажи:  {fmt_money(sales)}")
        print(f"Закупки:  {fmt_money(purchases)}")
        print(f"Сальдо:   {fmt_money(sales - purchases)}")
        return 0

    except SQLAlchemyError as exc:
        print("[ERROR] Ошибка подключения или запроса к MySQL:")
        print(exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
