"""The industry donut inside report module 05 — Final Analytics.

Kept apart from :mod:`.final_analytics` because it is a self-contained component with its own
formula version and its own chart-snapshot contract (rules document §4.3): structured data, never
a screenshot. Everything a renderer needs is resolved here — ordering, the zero-weight filter, the
display string and a stable colour token. The renderer only lays the series out; it must not
regroup, re-sort or recompute.
"""

import hashlib
import json
from decimal import Decimal
from typing import Iterable

from .errors import CalculationError
from .formatting import DISPLAY_FORMAT_V1, display_percent

SECTOR_CHART_FORMULA_VERSION = "sector-weight-v1"

# Versioned template configuration, keyed by `formula_profile` (rules document §4.3: "legend
# order and colour come from versioned template configuration, not from database order or a
# hard-coded calculation"). Declaring the order keeps the legend stable month to month instead
# of reshuffling whenever two industries swap rank. The reference output orders the HSTECH
# breakdown Consumer Discretionary -> Information Technology -> Healthcare -> Industrials,
# which is *not* weight-descending: Information Technology carries the larger weight.
# Industries outside the list fall back to weight-descending with an ascending-code
# tie-breaker (SORT-001), so a newly mapped industry still lands somewhere deterministic.
INDUSTRY_DISPLAY_ORDER = {
    "hstech-2026.1": ["23", "70", "28", "10", "50"],
}


def sector_breakdown(rows: Iterable[dict], display_order: list[str] | None = None) -> list[dict]:
    """Aggregate constituent weight by effective top-level industry.

    ``display_order`` is the versioned template configuration; industries it does not name are
    ranked weight-descending with an ascending-code tie-breaker (SORT-001). Order used to fall
    out of ``sorted(totals.items())``, which sorted by HSICS code and produced a legend the
    reference output does not use.

    Only the report-date-effective mapping is accepted. A raw source ``sector`` string used to
    satisfy this function, which meant a chart could be aggregated on a taxonomy assignment that
    QC-003 had already refused.
    """
    ranking = list(display_order or [])
    totals: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        code = str(row.get("effective_industry_code") or "")
        label = str(row.get("effective_industry_name") or "")
        if not code or not label:
            raise CalculationError(
                "INDUSTRY_MAPPING_MISSING",
                f"Security {row.get('security_code')} has no effective industry mapping to aggregate by.",
                "constituents.effective_industry_code",
                "Import the report-date HSICS master, or correct the source industry code on this security.",
                str(row.get("security_code") or ""),
            )
        key = (code, label)
        totals[key] = totals.get(key, Decimal("0")) + Decimal(str(row["weight"]))
    def rank(item: tuple[tuple[str, str], Decimal]) -> tuple[int, int, Decimal, str]:
        code = item[0][0]
        configured = ranking.index(code) if code in ranking else len(ranking)
        return (0 if code in ranking else 1, configured, -item[1], code)

    return [
        {"code": key[0], "sector": key[1], "weight": str(value)}
        for key, value in sorted(totals.items(), key=rank)
    ]


def sector_chart_snapshot(sectors: list[dict], payload: dict | None = None) -> dict:
    """The `industry_breakdown` chart snapshot defined by the rules document §4.3."""
    payload = payload or {}
    master = payload.get("industry_master") or {}
    places = DISPLAY_FORMAT_V1["sector_weight_places"]
    # Zero-weight industries never reach the chart (rules document §4.3). This filter used to
    # live in the renderer, where HTML and DOCX each applied their own version of it.
    positive = [row for row in sectors if Decimal(str(row["weight"])) > 0]
    source = json.dumps(sectors, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    snapshot = {
        "schema_version": 2,
        "chart_code": "industry_breakdown",
        "chart_type": "donut",
        "snapshot_id": str(payload.get("snapshot_id") or ""),
        "snapshot_dataset_ids": _chart_dataset_ids(payload),
        "formula_version": str(payload.get("formula_version") or SECTOR_CHART_FORMULA_VERSION),
        "mapping_version": str(payload.get("mapping_version") or ""),
        "taxonomy": str(master.get("taxonomy") or ""),
        "taxonomy_version": str(master.get("version") or ""),
        "as_of_date": str(payload.get("as_of_date") or ""),
        "series": [],
        "input_checksum": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "alt_text": "",
    }
    total = sum((Decimal(str(row["weight"])) for row in positive), Decimal("0"))
    if total <= 0:
        return snapshot

    cursor = Decimal("0")
    for index, row in enumerate(positive):
        weight = Decimal(str(row["weight"]))
        code = str(row.get("code") or row.get("sector") or "")
        start = cursor
        cursor += weight / total * Decimal("360")
        end = Decimal("360") if index == len(positive) - 1 else cursor
        snapshot["series"].append({
            "code": code,
            "label": str(row.get("sector") or ""),
            "raw_value": str(weight),
            "unit": "RATIO",
            "display_value": f"{display_percent(weight, places)}%",
            "sort_order": index + 1,
            # Bound to the industry, not to the position in the list. A positional index made
            # an industry change colour whenever the constituent set changed.
            "color_token": f"industry.hsics.{code}",
            "start_angle": str(start),
            "end_angle": str(end),
        })
    summary = ", ".join(f"{row['label']} {row['display_value']}" for row in snapshot["series"])
    snapshot["alt_text"] = f"Index sector breakdown: {summary}"
    return snapshot


def _chart_dataset_ids(payload: dict) -> list[str]:
    """Persisted SnapshotDataset ids behind the chart, when the caller knows them.

    ``calculate_snapshot`` stays free of database access, so ``run_calculation`` seeds
    ``snapshot_dataset_ids`` on the payload. Direct callers get the logical types instead of a
    fabricated id.
    """
    known = payload.get("snapshot_dataset_ids") or {}
    return sorted(
        str(known.get(dataset_type) or dataset_type)
        for dataset_type in ("constituent_snapshot", "industry_master")
    )
