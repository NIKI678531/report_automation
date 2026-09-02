from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def _decimal(value: Any, field: str, row_number: int) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("%", ""))
    except InvalidOperation as error:
        raise ValueError(f"Row {row_number}: {field} is not numeric") from error


def _required(row: dict[str, Any], field: str, row_number: int) -> str:
    value = row.get(field)
    if value in (None, ""):
        raise ValueError(f"Row {row_number}: {field} is required")
    text = str(value).strip()
    if text.startswith(("=", "+", "@")):
        raise ValueError(f"Row {row_number}: {field} contains an unsafe spreadsheet formula")
    return text


def _date(value: Any, field: str, row_number: int) -> date:
    text = _required({field: value}, field, row_number)
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"Row {row_number}: {field} must use YYYY-MM-DD or YYYYMMDD")


def _boolean(value: Any, field: str, row_number: int) -> bool:
    normalized = str(value or "").strip().upper()
    if normalized in {"1", "TRUE", "Y", "YES"}:
        return True
    if normalized in {"0", "FALSE", "N", "NO"}:
        return False
    raise ValueError(f"Row {row_number}: {field} must be true/false, yes/no, or 1/0")


def _records_from_csv(data: bytes) -> list[dict[str, Any]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def _parse_total_return_rows(data: bytes, report_date: date) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    seen: set[tuple[str, date]] = set()
    roles: set[str] = set()
    for index, row in enumerate(_records_from_csv(data), start=2):
        role = _required(row, "instrument_role", index).upper()
        if role not in {"FUND", "BENCHMARK"}:
            raise ValueError(f"Row {index}: instrument_role must be FUND or BENCHMARK")
        trade_date = _date(row.get("trade_date"), "trade_date", index)
        if trade_date > report_date:
            raise ValueError(f"Row {index}: trade_date cannot be later than report_date")
        key = (role, trade_date)
        if key in seen:
            raise ValueError(f"Row {index}: duplicate {role}/{trade_date.isoformat()} series point")
        seen.add(key)
        roles.add(role)
        total_return_value = _decimal(row.get("total_return_value"), "total_return_value", index)
        if total_return_value is None or total_return_value <= 0:
            raise ValueError(f"Row {index}: total_return_value must be greater than zero")
        series_type = _required(row, "series_type", index).replace("_", " ").upper()
        if series_type != "TOTAL RETURN":
            raise ValueError(f"Row {index}: series_type must be Total Return")
        series.append({
            "instrument_role": role,
            "instrument_code": _required(row, "instrument_code", index),
            "trade_date": trade_date.isoformat(),
            "total_return_value": str(total_return_value),
            "series_type": "Total Return",
            "currency": _required(row, "currency", index).upper(),
            "source": _required(row, "source", index),
        })
    if roles != {"FUND", "BENCHMARK"}:
        raise ValueError("Total Return Series requires both FUND and BENCHMARK observations")
    currencies = {row["currency"] for row in series}
    if len(currencies) != 1:
        raise ValueError("FUND and BENCHMARK series must use the same currency")
    series.sort(key=lambda row: (row["trade_date"], row["instrument_role"]))
    return series


def parse_total_return_series(filename: str, data: bytes, report_date: date) -> dict[str, Any]:
    if Path(filename).suffix.lower() != ".csv":
        raise ValueError("Total Return Series accepts CSV files only.")
    return {"total_return_series": _parse_total_return_rows(data, report_date)}


def parse_fund_kpi_daily(filename: str, data: bytes, report_date: date) -> dict[str, Any]:
    if Path(filename).suffix.lower() != ".csv":
        raise ValueError("Fund KPI Daily accepts CSV files only.")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, date]] = set()
    for index, row in enumerate(_records_from_csv(data), start=2):
        metric_code = _required(row, "metric_code", index).upper()
        if metric_code not in {"AUM", "DAILY_TURNOVER"}:
            raise ValueError(f"Row {index}: metric_code must be AUM or DAILY_TURNOVER")
        metric_date = _date(row.get("metric_date"), "metric_date", index)
        if metric_date > report_date:
            raise ValueError(f"Row {index}: metric_date cannot be later than report_date")
        if (metric_date.year, metric_date.month) != (report_date.year, report_date.month):
            raise ValueError(f"Row {index}: metric_date must be in the report month")
        key = (metric_code, metric_date)
        if key in seen:
            raise ValueError(f"Row {index}: duplicate KPI {metric_code}/{metric_date.isoformat()}")
        seen.add(key)
        value = _decimal(row.get("value"), "value", index)
        if value is None or value < 0:
            raise ValueError(f"Row {index}: KPI value must be zero or greater")
        rows.append({
            "metric_code": metric_code,
            "metric_date": metric_date.isoformat(),
            "value": str(value),
            "unit": _required(row, "unit", index),
            "currency": _required(row, "currency", index).upper(),
            "source": _required(row, "source", index),
        })
    if not any(row["metric_code"] == "AUM" for row in rows):
        raise ValueError("Fund KPI Daily requires an AUM observation")
    if not any(row["metric_code"] == "DAILY_TURNOVER" for row in rows):
        raise ValueError("Fund KPI Daily requires at least one DAILY_TURNOVER observation")
    rows.sort(key=lambda row: (row["metric_date"], row["metric_code"]))
    return {"fund_kpis": rows}


def parse_trading_calendar(filename: str, data: bytes, report_date: date) -> dict[str, Any]:
    if Path(filename).suffix.lower() != ".csv":
        raise ValueError("Trading Calendar accepts CSV files only.")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, date]] = set()
    for index, row in enumerate(_records_from_csv(data), start=2):
        market = _required(row, "market", index).upper()
        calendar_date = _date(row.get("date"), "date", index)
        if (calendar_date.year, calendar_date.month) != (report_date.year, report_date.month):
            raise ValueError(f"Row {index}: date must be in the report month")
        key = (market, calendar_date)
        if key in seen:
            raise ValueError(f"Row {index}: duplicate calendar date {market}/{calendar_date.isoformat()}")
        seen.add(key)
        rows.append({
            "market": market,
            "date": calendar_date.isoformat(),
            "is_trading_day": _boolean(row.get("is_trading_day"), "is_trading_day", index),
            "source": _required(row, "source", index),
        })
    if not rows or not any(row["is_trading_day"] for row in rows):
        raise ValueError("Trading Calendar requires at least one trading day")
    rows.sort(key=lambda row: (row["date"], row["market"]))
    return {"trading_calendar": rows}


def parse_index_events(filename: str, data: bytes, report_date: date) -> dict[str, Any]:
    if Path(filename).suffix.lower() != ".csv":
        raise ValueError("Index Events accepts CSV files only.")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, date]] = set()
    for index, row in enumerate(_records_from_csv(data), start=2):
        index_code = _required(row, "index_code", index).upper()
        event_type = _required(row, "event_type", index).upper()
        if event_type != "REBALANCE":
            raise ValueError(f"Row {index}: event_type must be REBALANCE")
        effective_date = _date(row.get("effective_date"), "effective_date", index)
        announcement_text = str(row.get("announcement_date") or "").strip()
        announcement_date = _date(announcement_text, "announcement_date", index) if announcement_text else None
        if announcement_date and announcement_date > report_date:
            raise ValueError(f"Row {index}: announcement_date cannot be later than report_date")
        key = (index_code, event_type, effective_date)
        if key in seen:
            raise ValueError(f"Row {index}: duplicate index event {index_code}/{event_type}/{effective_date.isoformat()}")
        seen.add(key)
        rows.append({
            "index_code": index_code,
            "event_type": event_type,
            "announcement_date": announcement_date.isoformat() if announcement_date else None,
            "effective_date": effective_date.isoformat(),
            "source": _required(row, "source", index),
        })
    if not rows:
        raise ValueError("Index Events requires at least one event")
    rows.sort(key=lambda row: (row["effective_date"], row["index_code"], row["event_type"]))
    return {"index_events": rows}


def diff_constituents(candidate: list[dict], active: list[dict]) -> dict[str, Any]:
    old = {row["security_code"]: row for row in active}
    new = {row["security_code"]: row for row in candidate}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = []
    numeric_fields = {"close_price", "weight"}
    for code in sorted(set(new) & set(old)):
        fields = {}
        for key in ("name_en", "close_price", "weight", "source_codes"):
            old_value = old[code].get(key)
            new_value = new[code].get(key)
            if key in numeric_fields and old_value is not None and new_value is not None:
                equal = Decimal(str(old_value)) == Decimal(str(new_value))
            else:
                equal = old_value == new_value
            if not equal:
                fields[key] = {"old": old_value, "new": new_value}
        if fields:
            changed.append({"security_code": code, "fields": fields})
    return {"added": added, "removed": removed, "changed": changed, "summary": {"added": len(added), "removed": len(removed), "changed": len(changed)}}


def diff_dataset(dataset_type: str, candidate: dict[str, Any], active: dict[str, Any]) -> dict[str, Any]:
    if dataset_type != "constituents":
        raise ValueError(f"Unsupported diff dataset type: {dataset_type}")
    return diff_constituents(candidate.get("constituents", []), active.get("constituents", []))
