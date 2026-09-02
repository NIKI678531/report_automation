"""Copy the monthly-turnover table from a DA Report MySQL dump into its SQLite snapshot.

This is an offline refresh utility for the approved DA Report object. The application continues
to read only the SQLite snapshot (or its object-storage copy); it never depends on a container
filesystem dump at runtime.
"""

from __future__ import annotations

import argparse
import ast
import sqlite3
from pathlib import Path


INSERT_PREFIX = "INSERT INTO `market_monthly_turnovers` VALUES "
COLUMNS = (
    "id",
    "bloomberg_ticker",
    "calendar_ticker",
    "month_start",
    "period_start",
    "period_end",
    "total_turnover",
    "trading_days",
    "average_daily_turnover",
    "currency",
    "fetched_at",
)


def read_rows(dump_path: Path) -> list[tuple]:
    with dump_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(INSERT_PREFIX):
                values = line[len(INSERT_PREFIX):].strip()
                if not values.endswith(";"):
                    raise ValueError("market_monthly_turnovers INSERT is not terminated")
                parsed = ast.literal_eval(f"[{values[:-1]}]")
                rows = [tuple(row) for row in parsed]
                if not rows or any(len(row) != len(COLUMNS) for row in rows):
                    raise ValueError("market_monthly_turnovers rows do not match the expected schema")
                return rows
    raise ValueError("market_monthly_turnovers INSERT was not found in the dump")


def import_rows(sqlite_path: Path, rows: list[tuple]) -> None:
    connection = sqlite3.connect(sqlite_path)
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS market_monthly_turnovers (
                id INTEGER PRIMARY KEY,
                bloomberg_ticker TEXT NOT NULL,
                calendar_ticker TEXT NOT NULL,
                month_start TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                total_turnover NUMERIC NOT NULL,
                trading_days INTEGER NOT NULL,
                average_daily_turnover NUMERIC NOT NULL,
                currency TEXT,
                fetched_at TEXT NOT NULL,
                UNIQUE (bloomberg_ticker, month_start)
            )
        """)
        connection.executemany("""
            INSERT INTO market_monthly_turnovers (
                id, bloomberg_ticker, calendar_ticker, month_start, period_start, period_end,
                total_turnover, trading_days, average_daily_turnover, currency, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bloomberg_ticker, month_start) DO UPDATE SET
                calendar_ticker=excluded.calendar_ticker,
                period_start=excluded.period_start,
                period_end=excluded.period_end,
                total_turnover=excluded.total_turnover,
                trading_days=excluded.trading_days,
                average_daily_turnover=excluded.average_daily_turnover,
                currency=excluded.currency,
                fetched_at=excluded.fetched_at
        """, rows)
        connection.commit()
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dump", type=Path, help="DA Report MySQL dump")
    parser.add_argument("sqlite", type=Path, help="DA Report SQLite snapshot to update")
    args = parser.parse_args()
    rows = read_rows(args.dump)
    import_rows(args.sqlite, rows)
    print(f"Imported {len(rows)} monthly turnover rows into {args.sqlite}")


if __name__ == "__main__":
    main()
