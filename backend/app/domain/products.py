from __future__ import annotations

import csv
import io
from datetime import date


REQUIRED_COLUMNS = {
    "product_code",
    "ticker",
    "name_en",
    "constituent_index_code",
    "benchmark_instrument_code",
    "valid_from",
    "template_version",
    "design_token_version",
    "formula_profile",
}


def parse_product_catalog_csv(data: bytes) -> list[dict]:
    try:
        stream = io.StringIO(data.decode("utf-8-sig"))
    except UnicodeDecodeError as error:
        raise ValueError("Product catalog must be UTF-8 encoded.") from error
    reader = csv.DictReader(stream)
    columns = set(reader.fieldnames or [])
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    products: list[dict] = []
    versions: set[tuple[str, date]] = set()
    for line_number, raw in enumerate(reader, start=2):
        try:
            product_code = required(raw, "product_code").upper()
            valid_from = date.fromisoformat(required(raw, "valid_from"))
            valid_to_text = optional(raw, "valid_to")
            valid_to = date.fromisoformat(valid_to_text) if valid_to_text else None
            if valid_to and valid_to < valid_from:
                raise ValueError("valid_to cannot be before valid_from")
            version_key = (product_code, valid_from)
            if version_key in versions:
                raise ValueError(f"duplicate product version {product_code}/{valid_from.isoformat()}")
            versions.add(version_key)
            expected_count_text = optional(raw, "expected_constituent_count")
            display_order_text = optional(raw, "display_order")
            products.append({
                "product_code": product_code,
                "ticker": required(raw, "ticker").upper(),
                "name_en": required(raw, "name_en"),
                "name_zh_hant": optional(raw, "name_zh_hant") or None,
                "constituent_index_code": required(raw, "constituent_index_code").upper(),
                "constituent_index_name": optional(raw, "constituent_index_name") or None,
                "benchmark_instrument_code": required(raw, "benchmark_instrument_code").upper(),
                "benchmark_instrument_name": optional(raw, "benchmark_instrument_name") or None,
                "benchmark_code": required(raw, "constituent_index_code").upper(),
                "benchmark_name": optional(raw, "benchmark_instrument_name") or optional(raw, "constituent_index_name") or None,
                "currency": (optional(raw, "currency") or "HKD").upper(),
                "timezone": optional(raw, "timezone") or "Asia/Hong_Kong",
                "valid_from": valid_from,
                "valid_to": valid_to,
                "is_active": parse_bool(optional(raw, "is_active") or "true"),
                "display_order": int(display_order_text) if display_order_text else 0,
                "template_version": required(raw, "template_version"),
                "design_token_version": required(raw, "design_token_version"),
                "expected_constituent_count": int(expected_count_text) if expected_count_text else None,
                "formula_profile": required(raw, "formula_profile"),
                "source": "APPROVED_IMPORT",
            })
        except (ValueError, TypeError) as error:
            raise ValueError(f"Line {line_number}: {error}") from error
    if not products:
        raise ValueError("Product catalog is empty.")
    return products


def required(row: dict[str, str | None], field: str) -> str:
    value = optional(row, field)
    if not value:
        raise ValueError(f"{field} is required")
    return value


def optional(row: dict[str, str | None], field: str) -> str:
    return (row.get(field) or "").strip()


def parse_bool(value: str) -> bool:
    normalized = value.lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"invalid boolean value {value!r}")