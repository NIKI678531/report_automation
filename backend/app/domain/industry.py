from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import IndustryMasterRecord


LEVEL_WIDTH = {"INDUSTRY": 2, "SECTOR": 4, "SUBSECTOR": 6}


def normalize_hsics_code(value: Any, level: str) -> str:
    normalized_level = str(level).strip().upper()
    if normalized_level not in LEVEL_WIDTH:
        raise ValueError("level must be INDUSTRY, SECTOR or SUBSECTOR")
    text = unicodedata.normalize("NFKC", "" if value is None else str(value)).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if not re.fullmatch(r"\d+", text):
        raise ValueError(f"{normalized_level} code must contain digits only")
    width = LEVEL_WIDTH[normalized_level]
    if len(text) > width:
        raise ValueError(f"{normalized_level} code cannot exceed {width} digits")
    return text.zfill(width)


def _date(value: str, field: str, row_number: int, required: bool = True) -> date | None:
    text = str(value or "").strip()
    if not text and not required:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"Row {row_number}: {field} must use YYYY-MM-DD") from error


def _text(row: dict[str, str], field: str, row_number: int, required: bool = True) -> str | None:
    value = unicodedata.normalize("NFKC", str(row.get(field) or "")).strip()
    if required and not value:
        raise ValueError(f"Row {row_number}: {field} is required")
    if value.startswith(("=", "+", "@")):
        raise ValueError(f"Row {row_number}: {field} contains an unsafe spreadsheet formula")
    return value or None


def parse_industry_master_csv(data: bytes) -> list[dict[str, Any]]:
    records = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    if not records:
        raise ValueError("Industry master is empty")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row_number, raw in enumerate(records, start=2):
        taxonomy = str(_text(raw, "taxonomy", row_number)).upper()
        if taxonomy != "HSICS":
            raise ValueError(f"Row {row_number}: taxonomy must be HSICS")
        version = str(_text(raw, "version", row_number))
        level = str(_text(raw, "level", row_number)).upper()
        code = normalize_hsics_code(raw.get("code"), level)
        key = (level, code)
        if key in seen:
            raise ValueError(f"Row {row_number}: duplicate {level} code {code}")
        seen.add(key)
        expected_parent = None if level == "INDUSTRY" else code[:2] if level == "SECTOR" else code[:4]
        parent_code = str(raw.get("parent_code") or "").strip()
        if expected_parent:
            parent_level = "INDUSTRY" if level == "SECTOR" else "SECTOR"
            normalized_parent = normalize_hsics_code(parent_code or expected_parent, parent_level)
            if normalized_parent != expected_parent:
                raise ValueError(f"Row {row_number}: parent_code must match the code prefix {expected_parent}")
            parent_code = normalized_parent
        elif parent_code:
            raise ValueError(f"Row {row_number}: INDUSTRY rows cannot have parent_code")
        valid_from = _date(raw.get("valid_from", ""), "valid_from", row_number)
        valid_to = _date(raw.get("valid_to", ""), "valid_to", row_number, required=False)
        if valid_to and valid_to < valid_from:
            raise ValueError(f"Row {row_number}: valid_to cannot be earlier than valid_from")
        canonical = {
            "taxonomy": taxonomy,
            "version": version,
            "level": level,
            "code": code,
            "parent_code": parent_code or None,
            "name_en": _text(raw, "name_en", row_number),
            "name_zh_hant": _text(raw, "name_zh_hant", row_number, required=False),
            "valid_from": valid_from,
            "valid_to": valid_to,
            "source": _text(raw, "source", row_number),
            "source_record_key": str(_text(raw, "source_record_key", row_number, required=False) or f"{level}:{code}"),
        }
        digest_value = {key: value.isoformat() if isinstance(value, date) else value for key, value in canonical.items()}
        canonical["checksum"] = hashlib.sha256(json.dumps(digest_value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        rows.append(canonical)

    identity = {(row["taxonomy"], row["version"], row["valid_from"], row["valid_to"], row["source"]) for row in rows}
    if len(identity) != 1:
        raise ValueError("One industry master file must contain one taxonomy version, effective range and source")
    available = {(row["level"], row["code"]) for row in rows}
    for row in rows:
        if row["level"] == "SECTOR" and ("INDUSTRY", row["parent_code"]) not in available:
            raise ValueError(f"SECTOR {row['code']} is missing parent INDUSTRY {row['parent_code']}")
        if row["level"] == "SUBSECTOR" and ("SECTOR", row["parent_code"]) not in available:
            raise ValueError(f"SUBSECTOR {row['code']} is missing parent SECTOR {row['parent_code']}")
    return rows


def effective_hsics_records(db: Session, as_of_date: date) -> list[IndustryMasterRecord]:
    return list(db.scalars(select(IndustryMasterRecord).where(
        IndustryMasterRecord.taxonomy == "HSICS",
        IndustryMasterRecord.valid_from <= as_of_date,
        or_(IndustryMasterRecord.valid_to.is_(None), IndustryMasterRecord.valid_to >= as_of_date),
    )))


def map_effective_hsics(db: Session, payload: dict[str, Any], report_date: date) -> list[dict[str, Any]]:
    records = effective_hsics_records(db, report_date)
    if not records:
        return []
    versions = {row.version for row in records}
    if len(versions) != 1:
        return [{
            "error_code": "IND-001",
            "severity": "BLOCKING",
            "entity_id": None,
            "message": f"{len(versions)} HSICS versions are effective on {report_date.isoformat()}.",
            "fix_hint": "Correct the version effective dates so exactly one HSICS version applies.",
        }]
    industries = {row.code: row for row in records if row.level == "INDUSTRY"}
    findings: list[dict[str, Any]] = []
    for constituent in payload.get("constituents", []):
        source_codes = constituent.get("source_codes") if isinstance(constituent.get("source_codes"), dict) else {}
        raw_code = constituent.get("source_industry_code") or source_codes.get("hsics_industry")
        try:
            code = normalize_hsics_code(raw_code, "INDUSTRY")
        except ValueError:
            code = ""
        industry = industries.get(code)
        if not industry:
            findings.append({
                "error_code": "IND-002",
                "severity": "BLOCKING",
                "entity_id": str(constituent.get("security_code") or ""),
                "message": f"Security {constituent.get('security_code')} has no effective HSICS industry mapping.",
                "fix_hint": "Correct the source industry code or import the complete report-date HSICS master.",
            })
            continue
        constituent["source_industry_code"] = code
        constituent["effective_industry_code"] = code
        constituent["effective_industry_name"] = industry.name_en
        constituent["industry_taxonomy"] = industry.taxonomy
        constituent["industry_taxonomy_version"] = industry.version
        constituent["sector"] = industry.name_en
    version = next(iter(versions))
    payload["industry_master"] = {
        "taxonomy": "HSICS",
        "version": version,
        "as_of_date": report_date.isoformat(),
        "record_count": len(records),
        "checksum": hashlib.sha256("".join(sorted(row.checksum for row in records)).encode()).hexdigest(),
    }
    return findings