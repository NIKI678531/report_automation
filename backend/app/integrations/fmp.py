"""Financial Modeling Prep adapter for Page 04 constituent period returns.

The provider's dividend-adjusted EOD series is treated as a Total Return price series.  The
adapter resolves one common Hong Kong market boundary for each period, calculates decimal-ratio
returns, and retains the exact source observations in lineage so every displayed value can be
reproduced without persisting a vendor file.
"""

from __future__ import annotations

import hashlib
import json
import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings


RETURN_FIELDS = ("return_1m", "return_3m", "return_6m", "return_ytd")
ENDPOINT_PATH = "historical-price-eod/dividend-adjusted"
SOURCE_NAME = "Financial Modeling Prep dividend-adjusted EOD"
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.^=_-]+(?:\.[A-Z0-9]+)?$")


class FmpProviderError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 503, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def is_configured() -> bool:
    return settings.fmp_constituent_returns_enabled and bool(settings.fmp_api_key)


def _provider_url() -> str:
    parsed = urlparse(settings.fmp_base_url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in settings.fmp_allowed_hosts:
        raise FmpProviderError(
            "FMP_HOST_NOT_ALLOWED",
            "The Financial Modeling Prep base URL is not an approved HTTPS host.",
        )
    return f"{settings.fmp_base_url.rstrip('/')}/{ENDPOINT_PATH}"


def _shift_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    source_month_end = value.day == monthrange(value.year, value.month)[1]
    day = monthrange(year, month)[1] if source_month_end else min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def period_targets(report_date: date) -> dict[str, date]:
    return {
        "return_1m": _shift_months(report_date, 1),
        "return_3m": _shift_months(report_date, 3),
        "return_6m": _shift_months(report_date, 6),
        "return_ytd": date(report_date.year - 1, 12, 31),
    }


def fmp_symbol(row: dict[str, Any]) -> str:
    ticker = str(row.get("ticker") or "").strip().upper().replace(" ", "")
    if ticker.endswith(".HK") and _SYMBOL_PATTERN.fullmatch(ticker):
        return ticker
    code = re.sub(r"\D", "", str(row.get("security_code") or ""))
    if not code:
        raise FmpProviderError(
            "FMP_SYMBOL_MISSING",
            f"No FMP symbol can be derived for constituent {row.get('name_en') or 'without a name'}.",
            422,
        )
    width = max(4, len(code))
    symbol = f"{int(code):0{width}d}.HK"
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise FmpProviderError("FMP_SYMBOL_INVALID", "A constituent resolved to an invalid FMP symbol.", 422)
    return symbol


def _parse_series(symbol: str, payload: Any, report_date: date) -> dict[date, Decimal]:
    if not isinstance(payload, list):
        raise FmpProviderError(
            "FMP_RESPONSE_INVALID",
            "Financial Modeling Prep returned an unexpected response shape.",
            502,
        )
    series: dict[date, Decimal] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        returned_symbol = str(item.get("symbol") or "").strip().upper()
        if returned_symbol and returned_symbol != symbol:
            continue
        try:
            trade_date = date.fromisoformat(str(item["date"]))
            adjusted_close = Decimal(str(item["adjClose"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
        if trade_date <= report_date and adjusted_close > 0:
            series[trade_date] = adjusted_close
    return series


def _fetch_series(
    client: httpx.Client,
    symbol: str,
    from_date: date,
    report_date: date,
) -> dict[date, Decimal]:
    try:
        response = client.get(
            _provider_url(),
            params={"symbol": symbol, "from": from_date.isoformat(), "to": report_date.isoformat()},
            headers={"apikey": settings.fmp_api_key or "", "Accept": "application/json"},
        )
    except httpx.TimeoutException:
        raise FmpProviderError("FMP_TIMEOUT", "Financial Modeling Prep timed out.", 504, retryable=True) from None
    except httpx.RequestError:
        raise FmpProviderError("FMP_UNAVAILABLE", "Financial Modeling Prep could not be reached.", 502, retryable=True) from None
    if response.status_code in {401, 403}:
        raise FmpProviderError("FMP_AUTH_FAILED", "Financial Modeling Prep rejected the configured API key.", 502)
    if response.status_code == 402:
        raise FmpProviderError("FMP_QUOTA_EXCEEDED", "The Financial Modeling Prep plan quota is exhausted.", 503)
    if response.status_code == 429:
        raise FmpProviderError("FMP_RATE_LIMITED", "Financial Modeling Prep rate limit was reached.", 503, retryable=True)
    if response.status_code >= 500:
        raise FmpProviderError("FMP_UNAVAILABLE", "Financial Modeling Prep is unavailable.", 502, retryable=True)
    if response.status_code >= 400:
        raise FmpProviderError("FMP_REQUEST_REJECTED", "Financial Modeling Prep rejected a constituent-price request.", 502)
    try:
        payload = response.json()
    except ValueError:
        raise FmpProviderError("FMP_RESPONSE_INVALID", "Financial Modeling Prep returned invalid JSON.", 502) from None
    return _parse_series(symbol, payload, report_date)


def _latest_on_or_before(series: dict[date, Decimal], boundary: date) -> tuple[date, Decimal] | None:
    candidates = [trade_date for trade_date in series if trade_date <= boundary]
    if not candidates:
        return None
    trade_date = max(candidates)
    return trade_date, series[trade_date]


def load_constituent_returns(
    constituents: list[dict[str, Any]],
    report_date: date,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    if not settings.fmp_constituent_returns_enabled:
        raise FmpProviderError("FMP_DISABLED", "Automatic FMP constituent returns are disabled.", 503)
    if not settings.fmp_api_key:
        raise FmpProviderError("FMP_NOT_CONFIGURED", "Financial Modeling Prep is not configured.", 503)
    if not constituents:
        raise FmpProviderError("FMP_CONSTITUENTS_REQUIRED", "A constituent list is required before FMP returns can be loaded.", 422)

    targets = period_targets(report_date)
    query_start = min(targets.values()) - timedelta(days=settings.fmp_boundary_lookback_days)
    request_client = client or httpx.Client(timeout=settings.fmp_timeout_seconds)
    series_by_code: dict[str, tuple[str, dict[date, Decimal]]] = {}
    try:
        for row in constituents:
            code = str(row.get("security_code") or "").strip()
            symbol = fmp_symbol(row)
            series_by_code[code] = (
                symbol,
                _fetch_series(request_client, symbol, query_start, report_date),
            )
    finally:
        if client is None:
            request_client.close()

    market_dates = sorted({
        trade_date
        for _symbol, series in series_by_code.values()
        for trade_date in series
        if trade_date <= report_date
    })
    if not market_dates:
        raise FmpProviderError(
            "FMP_DATA_NOT_FOUND",
            "Financial Modeling Prep returned no dividend-adjusted EOD prices for the selected constituents and month.",
            422,
        )
    period_end = market_dates[-1]
    starts: dict[str, date] = {}
    for field, target in targets.items():
        candidates = [trade_date for trade_date in market_dates if trade_date <= target]
        if not candidates:
            raise FmpProviderError(
                "FMP_PERIOD_BOUNDARY_MISSING",
                f"Financial Modeling Prep has no market date on or before {target.isoformat()} for {field}.",
                422,
            )
        starts[field] = candidates[-1]

    rows: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    numeric_values = 0
    for constituent in constituents:
        code = str(constituent.get("security_code") or "").strip()
        symbol, series = series_by_code[code]
        end_observation = _latest_on_or_before(series, period_end)
        output: dict[str, Any] = {"security_code": code}
        lineage_row: dict[str, Any] = {
            "security_code": code,
            "name_en": constituent.get("name_en"),
            "requested_ticker": constituent.get("ticker"),
            "resolved_symbol": symbol,
            "end": None,
            "starts": {},
        }
        if end_observation:
            lineage_row["end"] = {
                "date": end_observation[0].isoformat(),
                "adj_close": str(end_observation[1]),
            }
        for field in RETURN_FIELDS:
            start_observation = _latest_on_or_before(series, starts[field])
            lineage_row["starts"][field] = (
                {"date": start_observation[0].isoformat(), "adj_close": str(start_observation[1])}
                if start_observation else None
            )
            if not end_observation:
                output[field] = None
                output[f"{field}_missing_reason"] = "SOURCE_NA"
                missing.append({"security_code": code, "ticker": symbol, "field": field, "reason": "SOURCE_NA"})
            elif not start_observation:
                output[field] = None
                output[f"{field}_missing_reason"] = "INSUFFICIENT_HISTORY"
                missing.append({"security_code": code, "ticker": symbol, "field": field, "reason": "INSUFFICIENT_HISTORY"})
            else:
                output[field] = str(end_observation[1] / start_observation[1] - Decimal("1"))
                numeric_values += 1
        rows.append(output)
        observations.append(lineage_row)

    if numeric_values == 0:
        raise FmpProviderError(
            "FMP_DATA_NOT_FOUND",
            "Financial Modeling Prep returned no usable period-return observations.",
            422,
        )
    periods = {
        "starts": {field: value.isoformat() for field, value in starts.items()},
        "end": period_end.isoformat(),
        "source": SOURCE_NAME,
    }
    checksum_payload = json.dumps(
        {"rows": rows, "periods": periods, "observations": observations},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    findings = []
    if missing:
        findings.append({
            "check_id": "FMP_CONSTITUENT_RETURN_COVERAGE",
            "error_code": "FMP_CONSTITUENT_RETURN_COVERAGE",
            "severity": "WARNING",
            "status": "WARNING",
            "message": f"FMP could not calculate {len(missing)} of {len(rows) * len(RETURN_FIELDS)} constituent period returns.",
            "actual": {"missing": missing, "numeric_values": numeric_values},
            "threshold": {"requested_values": len(rows) * len(RETURN_FIELDS)},
            "fix_hint": "Keep legitimate pre-listing periods as N/A; otherwise verify the ticker mapping and FMP coverage.",
        })
    return {
        "constituent_returns": rows,
        "return_periods": periods,
        "datasets": {
            "constituent_returns": {
                "source_type": "FMP_API",
                "source_name": SOURCE_NAME,
                "source_object": f"{settings.fmp_base_url.rstrip('/')}/{ENDPOINT_PATH}",
                "row_count": len(rows),
                "checksum": hashlib.sha256(checksum_payload.encode("utf-8")).hexdigest(),
                "mapping_version": "fmp-hk-ticker-v1",
                "lineage": {
                    "source_system": "FINANCIAL_MODELING_PREP",
                    "endpoint": ENDPOINT_PATH,
                    "price_field": "adjClose",
                    "series_type": "TOTAL_RETURN",
                    "formula": "adjClose(period_end) / adjClose(period_start) - 1",
                    "requested_report_date": report_date.isoformat(),
                    "query_window": {"from": query_start.isoformat(), "to": report_date.isoformat()},
                    "periods": periods,
                    "observations": observations,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        },
        "_findings": findings,
    }
