"""Dataset slot registry: one authoritative source per snapshot field.

A monthly report is assembled from several files that each know a different part of the truth.
The HSTECH end-of-day CSV knows identity, price and weight but carries no returns; the Bloomberg
workbook knows returns on one sheet and GICS sectors on another. Uploading any one of them
produces an incomplete snapshot, which is expected rather than an error.

Each slot declares the snapshot fields it ``owns``. Applying a slot overlays only those fields
onto the active snapshot, so two sources can never silently write the same field
(AGENTS.md: "No implicit mixing of CDB and uploaded files").
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from openpyxl import load_workbook

from app.domain import imports
from app.domain.models import MappingProfile
from app.domain.validation import BLOCKING, INFO, WARNING, FindingCollector

# Fields the constituent-identity slot is authoritative for.
IDENTITY_FIELDS = ("security_code", "ticker", "name_en", "name_zh_hant", "close_price", "currency", "weight", "as_of_date", "source_codes")
RETURN_FIELDS = ("return_1m", "return_3m", "return_6m", "return_ytd")


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    title: str
    required: bool
    accepts: tuple[str, ...]
    owns: tuple[str, ...]
    parse: Callable[..., dict[str, Any]]
    description: str = ""


@dataclass(frozen=True)
class MappingCandidate:
    sheet: str | None
    header_row: int
    columns: dict[str, tuple[int, ...]]


def _normalize_header(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\s\r\n]+", " ", text).strip().casefold()
    return re.sub(r"[^\w%]+", " ", text).strip()


def _field_aliases(profile: MappingProfile, field: str) -> tuple[str, ...]:
    config = (profile.field_map or {}).get(field, {})
    aliases = config.get("aliases", []) if isinstance(config, dict) else []
    return tuple(_normalize_header(value) for value in aliases if str(value).strip())


def _mapped_value(row: dict[str, Any], field: str, profile: MappingProfile) -> Any:
    aliases = set(_field_aliases(profile, field))
    for key, value in row.items():
        if _normalize_header(key) in aliases and value not in (None, ""):
            return value
    return None


def _candidate_from_headers(headers: list[Any], profile: MappingProfile, sheet: str | None, header_row: int) -> MappingCandidate | None:
    normalized = [_normalize_header(value) for value in headers]
    required_fields = tuple((profile.selector or {}).get("required_fields", ()))
    columns: dict[str, tuple[int, ...]] = {}
    for field in profile.field_map or {}:
        aliases = set(_field_aliases(profile, field))
        matched = tuple(index for index, header in enumerate(normalized) if header and header in aliases)
        if matched:
            columns[field] = matched
    if required_fields and not all(columns.get(field) for field in required_fields):
        return None
    return MappingCandidate(sheet=sheet, header_row=header_row, columns=columns)


def mapping_candidates(profile: MappingProfile, filename: str, data: bytes) -> list[MappingCandidate]:
    suffix = Path(filename).suffix.lower()
    extensions = tuple(str(value).lower() for value in (profile.selector or {}).get("extensions", ()))
    if extensions and suffix not in extensions:
        return []
    if suffix == ".csv":
        records = imports._records_from_csv(data)
        headers = list(records[0]) if records else []
        candidate = _candidate_from_headers(headers, profile, None, 1)
        return [candidate] if candidate else []
    if suffix not in {".xlsx", ".xlsm"}:
        return []
    scan_rows = int((profile.selector or {}).get("header_scan_rows", 20))
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    candidates: list[MappingCandidate] = []
    try:
        for sheet in workbook.worksheets:
            for row_number, values in enumerate(
                sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, scan_rows), values_only=True),
                start=1,
            ):
                candidate = _candidate_from_headers(list(values), profile, sheet.title, row_number)
                if candidate:
                    candidates.append(candidate)
    finally:
        workbook.close()
    return candidates


def matching_profiles(profiles: list[MappingProfile], filename: str, data: bytes) -> list[tuple[MappingProfile, MappingCandidate]]:
    matches: list[tuple[MappingProfile, MappingCandidate]] = []
    for profile in profiles:
        candidates = mapping_candidates(profile, filename, data)
        if len(candidates) == 1:
            matches.append((profile, candidates[0]))
    return matches


def _normalize_code(value: Any) -> str:
    """`00700`, `700.0`, `700 HK Equity` all denote security 700."""
    text = str(value).strip().split()[0]
    if text.endswith(".0"):
        text = text[:-2]
    return text.lstrip("0") or "0"


def _check_accepts(spec: DatasetSpec, filename: str, collector: FindingCollector) -> bool:
    suffix = Path(filename).suffix.lower()
    if suffix in spec.accepts:
        return True
    collector.add(
        "DATASET_FILE_TYPE",
        f"{spec.title} accepts {', '.join(spec.accepts)} files; received '{suffix or filename}'.",
        fix_hint=f"Export the source as {spec.accepts[0]} and upload again.",
    )
    return False


# --------------------------------------------------------------------------------------
# index_constituents — HSTECH end-of-day constituent CSV
# --------------------------------------------------------------------------------------

def parse_index_constituents(filename: str, data: bytes, report_date: date, collector: FindingCollector, profile: MappingProfile | None = None) -> dict[str, Any]:
    if not _check_accepts(REGISTRY["index_constituents"], filename, collector):
        return {}
    if profile is None:
        collector.add("MAP-001", "No approved mapping profile was selected.", fix_hint="Confirm a unique mapping profile before parsing.")
        return {}
    records = imports._records_from_csv(data)
    rows: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(records, start=2):
        raw_code = _mapped_value(row, "security_code", profile)
        if raw_code in (None, ""):
            collector.add("IMPORT_ROW_INVALID", "Security code is required.", row=index, field="Lcal Cde", fix_hint="Every constituent row needs a local code.")
            continue
        code = _normalize_code(raw_code)
        if code in seen:
            collector.add("DUPLICATE_CONSTITUENT", f"Security {code} already appeared on row {seen[code]}.", row=index, field="Lcal Cde", entity_id=code, fix_hint="Remove the duplicate row; the index file must list each constituent once.")
            continue
        seen[code] = index
        weight = _profile_number(row, "weight", index, collector, profile, code)
        if weight is None:
            collector.add("IMPORT_ROW_INVALID", "Weight is required.", row=index, field="Pct Idx Wgt", entity_id=code, fix_hint="Supply the index weight for this constituent.")
            continue
        # `Pct Idx Wgt` is percent by definition, so the scale is read from the column, never
        # guessed from the magnitude: a 0.23% holding and a 0.23 ratio are indistinguishable
        # by size, and guessing silently corrupts every sub-1% constituent.
        weight_unit = str((profile.unit_map or {}).get("weight") or "").upper()
        if weight_unit == "PERCENT":
            weight /= 100
        elif weight_unit != "RATIO":
            collector.add("MAP-003", "Weight unit is not explicit in the mapping profile.", row=index, field="weight", entity_id=code, fix_hint="Set weight to PERCENT or RATIO in unit_map.")
            continue
        as_of = _row_date(_mapped_value(row, "as_of_date", profile) or _mapped_value(row, "trade_date", profile), index, collector) or report_date
        if as_of > report_date:
            collector.add("AS_OF_AFTER_REPORT_DATE", f"Row date {as_of.isoformat()} is later than the report date {report_date.isoformat()}.", row=index, field="Prod Dt", entity_id=code, fix_hint="Upload the end-of-day file for the report month.")
            continue
        rows.append({
            "security_code": code,
            "ticker": f"{code.zfill(4)}.HK",
            "name_en": str(_mapped_value(row, "name_en", profile) or code).strip(),
            "name_zh_hant": str(_mapped_value(row, "name_zh_hant", profile) or "").strip(),
            "close_price": str(value) if (value := _profile_number(row, "close_price", index, collector, profile, code)) is not None else None,
            "currency": str(_mapped_value(row, "currency", profile) or "").strip().upper(),
            "weight": str(weight),
            "as_of_date": as_of.isoformat(),
            # HSICS codes are kept for lineage only. They are not a sector name and must never be
            # rendered as one; the sector_mapping slot owns `sector`.
            "source_codes": {
                "hsics_industry": _text(_mapped_value(row, "source_industry_code", profile)),
                "hsics_sector": _text(_mapped_value(row, "source_sector_code", profile)),
            },
        })
    if not rows:
        collector.add("DATASET_EMPTY", "No usable constituent rows were found.", fix_hint="Check that the file is the HSTECH end-of-day constituent export.")
        return {}
    total = sum((Decimal(row["weight"]) for row in rows), Decimal("0"))
    if abs(total - Decimal("1")) > Decimal("0.0001"):
        collector.add("WEIGHT_SUM_OFF", f"Weights total {total:.6f} instead of 1.000000.", severity=WARNING, field="Pct Idx Wgt", fix_hint="Confirm the export covers the full index and uses percent weights.")
    rows.sort(key=lambda item: (-Decimal(item["weight"]), item["security_code"]))
    return {"constituents": rows}


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _profile_number(row: dict[str, Any], field: str, index: int, collector: FindingCollector, profile: MappingProfile, entity_id: str | None = None) -> Decimal | None:
    try:
        return imports._decimal(_mapped_value(row, field, profile), field, index)
    except ValueError as error:
        collector.add("IMPORT_ROW_INVALID", str(error), row=index, field=field, entity_id=entity_id, fix_hint="Remove thousands separators and any text from this cell.")
        return None


def _row_date(value: Any, index: int, collector: FindingCollector) -> date | None:
    if value in (None, ""):
        return None
    try:
        return imports._date(value, "as_of_date", index)
    except ValueError as error:
        collector.add("IMPORT_ROW_INVALID", str(error), row=index, field="as_of_date", fix_hint="Use YYYY-MM-DD or YYYYMMDD.")
        return None


# --------------------------------------------------------------------------------------
# constituent_returns — Bloomberg workbook, "Formula" sheet
# --------------------------------------------------------------------------------------

_RETURN_FIELDS = ("return_1m", "return_3m", "return_6m", "return_ytd")


def parse_constituent_returns(filename: str, data: bytes, report_date: date, collector: FindingCollector, profile: MappingProfile | None = None) -> dict[str, Any]:
    spec = REGISTRY["constituent_returns"]
    if not _check_accepts(spec, filename, collector):
        return {}
    if profile is None:
        collector.add("MAP-001", "No approved mapping profile was selected.", fix_hint="Confirm the Bloomberg layout profile before parsing its unlabelled code column.")
        return {}
    if Path(filename).suffix.lower() == ".csv":
        records = imports._records_from_csv(data)
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        starts: dict[str, str] = {}
        period_end: str | None = None
        source: str | None = None
        return_unit = str((profile.unit_map or {}).get("returns") or "").upper()
        if return_unit not in {"PERCENT", "RATIO"}:
            collector.add("MAP-003", "Return unit is not explicit in the mapping profile.", fix_hint="Set returns to PERCENT or RATIO in unit_map.")
            return {}
        period_fields = {
            "return_1m": "period_start_1m",
            "return_3m": "period_start_3m",
            "return_6m": "period_start_6m",
            "return_ytd": "period_start_ytd",
        }
        for index, record in enumerate(records, start=2):
            raw_code = _mapped_value(record, "security_code", profile)
            if raw_code in (None, ""):
                collector.add("IMPORT_ROW_INVALID", "Security code is required.", row=index, field="security_code", fix_hint="Every return row requires a security code.")
                continue
            code = _normalize_code(raw_code)
            if code in seen:
                collector.add("DUPLICATE_CONSTITUENT", f"Security {code} appears more than once.", row=index, entity_id=code, fix_hint="Keep one return row per security.")
                continue
            seen.add(code)
            item: dict[str, Any] = {"security_code": code}
            name = _text(_mapped_value(record, "name_en", profile))
            if name:
                item["_source_name"] = name
            for return_field, start_field in period_fields.items():
                raw_value = _mapped_value(record, return_field, profile)
                try:
                    value = imports._decimal(raw_value, return_field, index)
                except ValueError as error:
                    collector.add("IMPORT_ROW_INVALID", str(error), row=index, field=return_field, entity_id=code, fix_hint="Use a numeric return value.")
                    value = None
                item[return_field] = str(value / 100 if return_unit == "PERCENT" and value is not None else value) if value is not None else None
                parsed_start = _row_date(_mapped_value(record, start_field, profile), index, collector)
                if parsed_start:
                    existing_start = starts.get(return_field)
                    if existing_start and existing_start != parsed_start.isoformat():
                        collector.add("PERIOD_INCONSISTENT", f"{start_field} differs across rows.", row=index, field=start_field, entity_id=code, fix_hint="Use one common period boundary for the complete file.")
                    starts[return_field] = parsed_start.isoformat()
            parsed_end = _row_date(_mapped_value(record, "period_end", profile), index, collector)
            if parsed_end:
                if parsed_end > report_date:
                    collector.add("AS_OF_AFTER_REPORT_DATE", f"Period end {parsed_end.isoformat()} is later than the report date.", row=index, field="period_end", entity_id=code, fix_hint="Use returns ending no later than the report date.")
                if period_end and period_end != parsed_end.isoformat():
                    collector.add("PERIOD_INCONSISTENT", "period_end differs across rows.", row=index, field="period_end", entity_id=code, fix_hint="Use one common period end for the complete file.")
                period_end = parsed_end.isoformat()
            row_source = _text(_mapped_value(record, "source", profile))
            if row_source:
                if source and source != row_source:
                    collector.add("SOURCE_INCONSISTENT", "source differs across rows.", row=index, field="source", entity_id=code, fix_hint="Use one authoritative source per logical dataset.")
                source = row_source
            rows.append(item)
        if not rows:
            collector.add("DATASET_EMPTY", "No constituent return rows were found.", fix_hint="Use the standard constituent-return CSV template.")
            return {}
        return {"constituent_returns": rows, "return_periods": {"starts": starts, "end": period_end, "source": source}}
    candidates = mapping_candidates(profile, filename, data)
    if len(candidates) != 1:
        collector.add("MAP-001", f"Expected one return-table candidate; found {len(candidates)}.", fix_hint="Confirm the intended sheet/header row or create a new mapping profile.")
        return {}
    candidate = candidates[0]
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet = workbook[candidate.sheet]
        grid = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    # Row 2 carries the period boundaries the Bloomberg formulas were pulled against. They are
    # stored so a return can be traced back to the window it was computed over.
    period_starts: dict[str, str] = {}
    selected_columns = {field: candidate.columns[field][0] for field in _RETURN_FIELDS}
    duplicate_count = min(len(candidate.columns.get(field, ())) for field in _RETURN_FIELDS)
    if duplicate_count > 1:
        collector.add(
            "IGNORED_DUPLICATE_RETURN_GROUP",
            f"Found {duplicate_count} complete return column groups; the approved profile selects the first group only.",
            severity=INFO,
            fix_hint="Review the mapping profile if the vendor changes which group is authoritative.",
        )
    period_row_offset = int((profile.selector or {}).get("period_row_offset", -2))
    period_row_index = candidate.header_row - 1 + period_row_offset
    if 0 <= period_row_index < len(grid):
        header_dates = grid[period_row_index]
        for field, column in selected_columns.items():
            raw = header_dates[column] if column < len(header_dates) else None
            parsed = _row_date(raw, period_row_index + 1, collector)
            if parsed:
                period_starts[field] = parsed.isoformat()
        period_end_column = int((profile.selector or {}).get("period_end_column", 1)) - 1
        period_end = _row_date(header_dates[period_end_column] if period_end_column < len(header_dates) else None, period_row_index + 1, collector)
    else:
        period_end = None

    rows: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    code_column = int(((profile.field_map or {}).get("security_code") or {}).get("confirmed_column", 0)) - 1
    name_column = int(((profile.field_map or {}).get("name_en") or {}).get("confirmed_column", 0)) - 1
    if code_column < 0:
        collector.add("MAP-002", "The unlabelled security-code column has not been confirmed.", fix_hint="Set field_map.security_code.confirmed_column in the approved profile.")
        return {}
    first_data_row = candidate.header_row + 1
    return_unit = str((profile.unit_map or {}).get("returns") or "").upper()
    if return_unit not in {"PERCENT", "RATIO"}:
        collector.add("MAP-003", "Return unit is not explicit in the mapping profile.", fix_hint="Set returns to PERCENT or RATIO in unit_map.")
        return {}
    for offset, values in enumerate(grid[first_data_row - 1:], start=first_data_row):
        raw_code = values[code_column] if code_column < len(values) else None
        if raw_code in (None, ""):
            continue
        code = _normalize_code(raw_code)
        if code in seen:
            collector.add("DUPLICATE_CONSTITUENT", f"Security {code} already appeared on row {seen[code]}.", row=offset, entity_id=code, fix_hint="Remove the duplicate row from the Formula sheet.")
            continue
        seen[code] = offset
        item: dict[str, Any] = {"security_code": code}
        for field, column in selected_columns.items():
            raw = values[column] if column < len(values) else None
            if raw in (None, ""):
                collector.add("RETURN_MISSING", f"{field} is empty for security {code}.", severity=WARNING, row=offset, field=field, entity_id=code, fix_hint="Refresh the Bloomberg formula so every period returns a value.")
                item[field] = None
                continue
            try:
                value = imports._decimal(raw, field, offset)
            except ValueError as error:
                collector.add("IMPORT_ROW_INVALID", str(error), row=offset, field=field, entity_id=code, fix_hint="The cell must resolve to a number; check for #N/A from the Bloomberg add-in.")
                item[field] = None
                continue
            # Bloomberg CUST_TRR_RETURN_HOLDING_PER returns percent; canonical storage is 0-1.
            normalized_value = value / 100 if return_unit == "PERCENT" else value
            item[field] = str(normalized_value) if value is not None else None
        name = values[name_column] if 0 <= name_column < len(values) else None
        if name:
            item["_source_name"] = str(name).strip()
        rows.append(item)

    if not rows:
        collector.add("DATASET_EMPTY", "No return rows were found on the Formula sheet.", fix_hint="Check that the workbook is the monthly Bloomberg constituent update.")
        return {}
    return {
        "constituent_returns": rows,
        "return_periods": {"starts": period_starts, "end": period_end.isoformat() if period_end else None, "source": "Bloomberg CUST_TRR_RETURN_HOLDING_PER"},
    }


def _profiled_csv(parser: Callable[[str, bytes, date], dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def parse(filename: str, data: bytes, report_date: date, collector: FindingCollector, profile: MappingProfile | None = None) -> dict[str, Any]:
        del profile
        try:
            return parser(filename, data, report_date)
        except (ValueError, UnicodeError) as error:
            collector.add("IMPORT_PARSE_FAILED", str(error), fix_hint="Correct the reported row and upload again.")
            return {}
    return parse


REGISTRY: dict[str, DatasetSpec] = {
    "index_constituents": DatasetSpec(
        key="index_constituents",
        title="Index constituents",
        description="HSTECH end-of-day constituent export: identity, closing price and index weight.",
        required=True,
        accepts=(".csv",),
        owns=IDENTITY_FIELDS,
        parse=parse_index_constituents,
    ),
    "constituent_returns": DatasetSpec(
        key="constituent_returns",
        title="Constituent returns",
        description="Mapped monthly workbook: 1M / 3M / 6M / YTD total returns.",
        required=True,
        accepts=(".csv", ".xlsx", ".xlsm"),
        owns=RETURN_FIELDS,
        parse=parse_constituent_returns,
    ),
    "total_return_series": DatasetSpec(
        key="total_return_series",
        title="Total Return series",
        description="Official FUND and BENCHMARK daily Total Return observations.",
        required=True,
        accepts=(".csv",),
        owns=("total_return_series",),
        parse=_profiled_csv(imports.parse_total_return_series),
    ),
    "fund_kpi_daily": DatasetSpec(
        key="fund_kpi_daily",
        title="Fund KPI daily",
        description="Report-month AUM and daily turnover observations with explicit currency and units.",
        required=True,
        accepts=(".csv",),
        owns=("fund_kpis",),
        parse=_profiled_csv(imports.parse_fund_kpi_daily),
    ),
    "trading_calendar": DatasetSpec(
        key="trading_calendar",
        title="Trading calendar",
        description="Authoritative report-month trading-day calendar used for turnover coverage.",
        required=True,
        accepts=(".csv",),
        owns=("trading_calendar",),
        parse=_profiled_csv(imports.parse_trading_calendar),
    ),
    "index_events": DatasetSpec(
        key="index_events",
        title="Index events",
        description="Official future index events such as the next rebalancing date.",
        required=False,
        accepts=(".csv",),
        owns=("index_events",),
        parse=_profiled_csv(imports.parse_index_events),
    ),
}

REQUIRED_SLOTS = tuple(key for key, spec in REGISTRY.items() if spec.required)


def get_spec(dataset_type: str) -> DatasetSpec | None:
    return REGISTRY.get(dataset_type)


def parse(dataset_type: str, filename: str, data: bytes, report_date: date, profile: MappingProfile | None = None) -> tuple[dict[str, Any], FindingCollector]:
    """Parse an upload into a payload fragment plus every problem found along the way."""
    spec = REGISTRY[dataset_type]
    collector = FindingCollector()
    if profile is None:
        collector.add(
            "MAP-001",
            f"'{filename}' did not resolve to one approved {spec.title} mapping profile.",
            fix_hint="Review the mapping candidates and confirm or create a profile for this vendor format.",
        )
        return {}, collector
    payload = spec.parse(filename, data, report_date, collector, profile)
    return payload, collector
