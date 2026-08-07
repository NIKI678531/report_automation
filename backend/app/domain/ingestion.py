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
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

from openpyxl import load_workbook

from app.domain import imports
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
    # Headers that must all be present for the file to be recognised as this slot. Used both to
    # validate the upload and, in reverse, to tell the user which slot a misdirected file belongs to.
    required_headers: tuple[str, ...]
    owns: tuple[str, ...]
    parse: Callable[..., dict[str, Any]]
    description: str = ""
    sheet: str | None = None
    header_row: int = 1
    legacy: bool = False


def _normalize_code(value: Any) -> str:
    """`00700`, `700.0`, `700 HK Equity` all denote security 700."""
    text = str(value).strip().split()[0]
    if text.endswith(".0"):
        text = text[:-2]
    return text.lstrip("0") or "0"


def _sheet_headers(data: bytes, sheet: str | None, header_row: int) -> list[str]:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        name = sheet if sheet in workbook.sheetnames else workbook.sheetnames[0]
        rows = workbook[name].iter_rows(min_row=header_row, max_row=header_row, values_only=True)
        return [str(value).strip() for value in next(rows, ()) if value is not None]
    finally:
        workbook.close()


def file_headers(filename: str, data: bytes, spec: DatasetSpec | None = None) -> list[str]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        records = imports._records_from_csv(data)
        return [key for key in (records[0].keys() if records else ()) if key]
    if suffix in {".xlsx", ".xlsm"}:
        return _sheet_headers(data, spec.sheet if spec else None, spec.header_row if spec else 1)
    return []


def matches(spec: DatasetSpec, filename: str, data: bytes) -> bool:
    if Path(filename).suffix.lower() not in spec.accepts:
        return False
    if not spec.required_headers:
        return False
    present = {header.strip().lower() for header in file_headers(filename, data, spec)}
    return all(header.strip().lower() in present for header in spec.required_headers)


def identify(filename: str, data: bytes) -> list[str]:
    """Slot keys whose fingerprint this file matches.

    A single Bloomberg workbook legitimately feeds two slots (returns and sector mapping), so
    this returns every candidate rather than insisting on one.
    """
    return [key for key, spec in REGISTRY.items() if not spec.legacy and matches(spec, filename, data)]


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

def parse_index_constituents(filename: str, data: bytes, report_date: date, collector: FindingCollector) -> dict[str, Any]:
    if not _check_accepts(REGISTRY["index_constituents"], filename, collector):
        return {}
    records = imports._records_from_csv(data)
    rows: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(records, start=2):
        raw_code = imports._find(row, "security_code")
        if raw_code in (None, ""):
            collector.add("IMPORT_ROW_INVALID", "Security code is required.", row=index, field="Lcal Cde", fix_hint="Every constituent row needs a local code.")
            continue
        code = _normalize_code(raw_code)
        if code in seen:
            collector.add("DUPLICATE_CONSTITUENT", f"Security {code} already appeared on row {seen[code]}.", row=index, field="Lcal Cde", entity_id=code, fix_hint="Remove the duplicate row; the index file must list each constituent once.")
            continue
        seen[code] = index
        weight = _number(row, "weight", index, collector, code)
        if weight is None:
            collector.add("IMPORT_ROW_INVALID", "Weight is required.", row=index, field="Pct Idx Wgt", entity_id=code, fix_hint="Supply the index weight for this constituent.")
            continue
        # `Pct Idx Wgt` is percent by definition, so the scale is read from the column, never
        # guessed from the magnitude: a 0.23% holding and a 0.23 ratio are indistinguishable
        # by size, and guessing silently corrupts every sub-1% constituent.
        weight /= 100
        as_of = _row_date(row.get("Prod Dt") or row.get("Tradate"), index, collector) or report_date
        if as_of > report_date:
            collector.add("AS_OF_AFTER_REPORT_DATE", f"Row date {as_of.isoformat()} is later than the report date {report_date.isoformat()}.", row=index, field="Prod Dt", entity_id=code, fix_hint="Upload the end-of-day file for the report month.")
            continue
        rows.append({
            "security_code": code,
            "ticker": f"{code.zfill(4)}.HK",
            "name_en": str(imports._find(row, "name_en") or code).strip(),
            "name_zh_hant": str(imports._find(row, "name_zh_hant") or "").strip(),
            "close_price": _number(row, "close_price", index, collector, code),
            "currency": str(row.get("Lcal Ccy") or "HKD").strip().upper(),
            "weight": weight,
            "as_of_date": as_of.isoformat(),
            # HSICS codes are kept for lineage only. They are not a sector name and must never be
            # rendered as one; the sector_mapping slot owns `sector`.
            "source_codes": {"hsics_industry": _text(row.get("Industry")), "hsics_sector": _text(row.get("Sector"))},
        })
    if not rows:
        collector.add("DATASET_EMPTY", "No usable constituent rows were found.", fix_hint="Check that the file is the HSTECH end-of-day constituent export.")
        return {}
    total = sum(row["weight"] for row in rows)
    if abs(total - 1) > 0.0001:
        collector.add("WEIGHT_SUM_OFF", f"Weights total {total:.6f} instead of 1.000000.", severity=WARNING, field="Pct Idx Wgt", fix_hint="Confirm the export covers the full index and uses percent weights.")
    rows.sort(key=lambda item: (-item["weight"], item["security_code"]))
    return {"constituents": rows}


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _number(row: dict[str, Any], field: str, index: int, collector: FindingCollector, entity_id: str | None = None) -> float | None:
    try:
        return imports._decimal(imports._find(row, field), field, index)
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

_RETURN_COLUMNS = {"return_1m": 1, "return_3m": 2, "return_6m": 3, "return_ytd": 4}
_FORMULA_CODE_COLUMN = 12
_FORMULA_NAME_COLUMN = 13
_FORMULA_FIRST_DATA_ROW = 5


def parse_constituent_returns(filename: str, data: bytes, report_date: date, collector: FindingCollector) -> dict[str, Any]:
    spec = REGISTRY["constituent_returns"]
    if not _check_accepts(spec, filename, collector):
        return {}
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if spec.sheet not in workbook.sheetnames:
            collector.add(
                "SHEET_NOT_FOUND",
                f"Worksheet '{spec.sheet}' was not found; the workbook contains {', '.join(workbook.sheetnames)}.",
                fix_hint=f"Upload the Bloomberg workbook that contains the '{spec.sheet}' sheet.",
            )
            return {}
        sheet = workbook[spec.sheet]
        grid = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    # Row 2 carries the period boundaries the Bloomberg formulas were pulled against. They are
    # stored so a return can be traced back to the window it was computed over.
    period_starts: dict[str, str] = {}
    if len(grid) >= 2:
        header_dates = grid[1]
        for field, column in _RETURN_COLUMNS.items():
            raw = header_dates[column] if column < len(header_dates) else None
            parsed = _row_date(raw, 2, collector)
            if parsed:
                period_starts[field] = parsed.isoformat()
        period_end = _row_date(header_dates[0] if header_dates else None, 2, collector)
    else:
        period_end = None

    rows: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for offset, values in enumerate(grid[_FORMULA_FIRST_DATA_ROW - 1:], start=_FORMULA_FIRST_DATA_ROW):
        raw_code = values[_FORMULA_CODE_COLUMN] if _FORMULA_CODE_COLUMN < len(values) else None
        if raw_code in (None, ""):
            continue
        code = _normalize_code(raw_code)
        if code in seen:
            collector.add("DUPLICATE_CONSTITUENT", f"Security {code} already appeared on row {seen[code]}.", row=offset, entity_id=code, fix_hint="Remove the duplicate row from the Formula sheet.")
            continue
        seen[code] = offset
        item: dict[str, Any] = {"security_code": code}
        for field, column in _RETURN_COLUMNS.items():
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
            item[field] = value / 100 if value is not None else None
        name = values[_FORMULA_NAME_COLUMN] if _FORMULA_NAME_COLUMN < len(values) else None
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


# --------------------------------------------------------------------------------------
# sector_mapping — Bloomberg workbook, "Sheet1"
# --------------------------------------------------------------------------------------

def parse_sector_mapping(filename: str, data: bytes, report_date: date, collector: FindingCollector) -> dict[str, Any]:
    spec = REGISTRY["sector_mapping"]
    suffix = Path(filename).suffix.lower()
    if not _check_accepts(spec, filename, collector):
        return {}
    if suffix == ".csv":
        records = imports._records_from_csv(data)
    else:
        records = imports._records_from_xlsx(data, sheet_name=spec.sheet)
    rows: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(records, start=2):
        raw_code = imports._find(row, "security_code")
        if raw_code in (None, ""):
            continue
        code = _normalize_code(raw_code)
        sector = _text(imports._find(row, "sector"))
        if not sector:
            collector.add("SECTOR_MISSING", f"Security {code} has no GICS sector name.", severity=WARNING, row=index, field="GICS_SECTOR_NAME", entity_id=code, fix_hint="Refresh the Bloomberg GICS_SECTOR_NAME column for this security.")
            continue
        if code in seen:
            collector.add("DUPLICATE_CONSTITUENT", f"Security {code} already appeared on row {seen[code]}.", severity=WARNING, row=index, entity_id=code, fix_hint="Remove the duplicate row from the mapping sheet.")
            continue
        seen[code] = index
        rows.append({"security_code": code, "sector": sector, "source": "Bloomberg GICS_SECTOR_NAME"})
    if not rows:
        collector.add("DATASET_EMPTY", "No sector rows were found.", fix_hint="Check that the sheet has Code and GICS_SECTOR_NAME columns.")
        return {}
    return {"sector_mapping": rows}


# --------------------------------------------------------------------------------------
# sector_overrides — approved manual assignments
# --------------------------------------------------------------------------------------

def parse_sector_overrides(filename: str, data: bytes, report_date: date, collector: FindingCollector) -> dict[str, Any]:
    if not _check_accepts(REGISTRY["sector_overrides"], filename, collector):
        return {}
    records = imports._records_from_csv(data)
    rows: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(records, start=2):
        raw_code = row.get("security_code")
        if raw_code in (None, ""):
            collector.add("IMPORT_ROW_INVALID", "security_code is required.", row=index, field="security_code", fix_hint="Every override row must name the security it applies to.")
            continue
        code = _normalize_code(raw_code)
        sector = _text(row.get("sector"))
        reason = _text(row.get("reason"))
        source = _text(row.get("source"))
        if not sector:
            collector.add("IMPORT_ROW_INVALID", f"sector is required for security {code}.", row=index, field="sector", entity_id=code, fix_hint="State the approved sector name.")
            continue
        # An override replaces vendor data, so it is only auditable with a stated reason and source.
        if not reason or not source:
            collector.add("OVERRIDE_UNJUSTIFIED", f"Override for security {code} is missing a reason or source.", row=index, field="reason" if not reason else "source", entity_id=code, fix_hint="Record who approved this assignment and the document it came from.")
            continue
        if code in seen:
            collector.add("DUPLICATE_CONSTITUENT", f"Security {code} already appeared on row {seen[code]}.", row=index, entity_id=code, fix_hint="Keep one override row per security.")
            continue
        seen[code] = index
        rows.append({"security_code": code, "sector": sector, "reason": reason, "source": source})
    if not rows:
        collector.add("DATASET_EMPTY", "No override rows were found.", fix_hint="The file needs security_code, sector, reason and source columns.")
        return {}
    return {"sector_overrides": rows}


# --------------------------------------------------------------------------------------
# Legacy slots — kept so existing uploads and tests keep working unchanged.
# --------------------------------------------------------------------------------------

def _legacy(parser: Callable[..., dict[str, Any]], needs_report_date: bool) -> Callable[..., dict[str, Any]]:
    def parse(filename: str, data: bytes, report_date: date, collector: FindingCollector) -> dict[str, Any]:
        try:
            return parser(filename, data, report_date) if needs_report_date else parser(filename, data)
        except (ValueError, UnicodeError) as error:
            # Legacy parsers stop at the first bad row, so this is one finding by construction.
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
        required_headers=("Lcal Cde", "Pct Idx Wgt", "Cls Price"),
        owns=IDENTITY_FIELDS,
        parse=parse_index_constituents,
    ),
    "constituent_returns": DatasetSpec(
        key="constituent_returns",
        title="Constituent returns",
        description="Bloomberg monthly workbook, 'Formula' sheet: 1M / 3M / 6M / YTD total returns.",
        required=True,
        accepts=(".xlsx", ".xlsm"),
        required_headers=("1-month return (%)", "3-month return (%)", "YTD return (%)"),
        owns=RETURN_FIELDS,
        parse=parse_constituent_returns,
        sheet="Formula",
        header_row=4,
    ),
    "sector_mapping": DatasetSpec(
        key="sector_mapping",
        title="Sector mapping",
        description="Bloomberg monthly workbook, 'Sheet1': GICS_SECTOR_NAME per security.",
        required=True,
        accepts=(".xlsx", ".xlsm", ".csv"),
        required_headers=("Code", "GICS_SECTOR_NAME"),
        owns=("sector",),
        parse=parse_sector_mapping,
        sheet="Sheet1",
    ),
    "sector_overrides": DatasetSpec(
        key="sector_overrides",
        title="Sector overrides",
        description="Approved manual sector assignments for securities the vendor mapping does not cover.",
        required=False,
        accepts=(".csv",),
        required_headers=("security_code", "sector", "reason", "source"),
        owns=("sector",),
        parse=parse_sector_overrides,
    ),
    "constituents": DatasetSpec(
        key="constituents",
        title="Constituents (legacy combined)",
        description="Single-file constituent upload carrying identity, weight, sector and returns together.",
        required=False,
        accepts=(".csv", ".xlsx", ".xlsm"),
        required_headers=(),
        owns=(*IDENTITY_FIELDS, "sector", *RETURN_FIELDS),
        parse=_legacy(imports.parse_constituents, needs_report_date=False),
        legacy=True,
    ),
    "historical_performance": DatasetSpec(
        key="historical_performance",
        title="Historical performance",
        description="FUND and BENCHMARK Total Return series used to derive period returns.",
        required=False,
        accepts=(".csv",),
        required_headers=(),
        owns=("historical_performance", "total_return_series"),
        parse=_legacy(imports.parse_historical_performance, needs_report_date=True),
        legacy=True,
    ),
    "final_analytics": DatasetSpec(
        key="final_analytics",
        title="Final analytics",
        description="Mixed long-form dataset carrying constituents and fund KPIs.",
        required=False,
        accepts=(".csv",),
        required_headers=(),
        owns=(*IDENTITY_FIELDS, "sector", *RETURN_FIELDS, "fund_kpis"),
        parse=_legacy(imports.parse_final_analytics, needs_report_date=True),
        legacy=True,
    ),
}

REQUIRED_SLOTS = tuple(key for key, spec in REGISTRY.items() if spec.required)


def get_spec(dataset_type: str) -> DatasetSpec | None:
    return REGISTRY.get(dataset_type)


def parse(dataset_type: str, filename: str, data: bytes, report_date: date) -> tuple[dict[str, Any], FindingCollector]:
    """Parse an upload into a payload fragment plus every problem found along the way."""
    spec = REGISTRY[dataset_type]
    collector = FindingCollector()
    # Fingerprint first: uploading the Bloomberg workbook into the constituents slot is the most
    # common mistake, and naming the right slot is far more useful than a parse error.
    if spec.required_headers and not matches(spec, filename, data):
        candidates = [key for key in identify(filename, data) if key != dataset_type]
        if candidates:
            names = " or ".join(f"'{REGISTRY[key].title}'" for key in candidates)
            slots = " / ".join(candidates)
            hint = f"This file looks like {names}. Upload it to the {slots} slot instead."
        else:
            hint = f"{spec.title} needs the columns: {', '.join(spec.required_headers)}."
        collector.add(
            "DATASET_MISMATCH",
            f"'{filename}' does not have the columns {spec.title} requires.",
            fix_hint=hint,
            entity_id=candidates[0] if candidates else None,
        )
        return {}, collector
    payload = spec.parse(filename, data, report_date, collector)
    return payload, collector
