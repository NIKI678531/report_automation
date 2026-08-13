"""Report module 04 — Constituent Performance.

Rankings over the effective constituent set, plus the next rebalancing date printed beneath the
table. Each ranking carries its full tie-breaker chain, because two securities on the same return
must not swap places between one render and the next.
"""

from decimal import Decimal

BOTTOM_PERFORMER_COUNT = 3


def _with_return(rows: list[dict]) -> list[dict]:
    """Only constituents carrying a 1M return. A missing return is preserved as absent, never zero."""
    return [row for row in rows if row.get("return_1m") is not None]


def rank_by_weight(rows: list[dict]) -> list[dict]:
    """Weight-descending, ascending security code as the tie-breaker. Feeds the Top 10 holdings."""
    return sorted(rows, key=lambda row: (-Decimal(str(row["weight"])), str(row["security_code"])))


def rank_by_return(rows: list[dict]) -> list[dict]:
    """Return-descending, then weight-descending, then ascending security code."""
    return sorted(
        _with_return(rows),
        key=lambda row: (-Decimal(str(row["return_1m"])), -Decimal(str(row["weight"])), str(row["security_code"])),
    )


def bottom_by_return(rows: list[dict], limit: int = BOTTOM_PERFORMER_COUNT) -> list[dict]:
    """The worst performers, in *selection* order (worst first).

    Selection order and display order differ, so they are two functions. ``bottom_security_code``
    is taken from this list; the table renders :func:`order_for_display` instead.
    """
    return sorted(
        _with_return(rows),
        key=lambda row: (Decimal(str(row["return_1m"])), -Decimal(str(row["weight"])), str(row["security_code"])),
    )[:limit]


def order_for_display(rows: list[dict]) -> list[dict]:
    """Re-order an already-selected set return-descending, the order the report table prints."""
    return sorted(
        rows,
        key=lambda row: (-Decimal(str(row["return_1m"])), -Decimal(str(row["weight"])), str(row["security_code"])),
    )


def positive_weight_count(rows: list[dict]) -> int:
    """Unique holdings carrying a positive weight — the "Number of holdings" figure."""
    return sum(1 for row in rows if Decimal(str(row["weight"])) > 0)


def next_rebalancing_date(payload: dict, as_of_date: str) -> str | None:
    """The earliest future REBALANCE event for the constituent index, or ``None``.

    Scoped to ``constituent_index_code``: an index event carrying another index's code is lineage
    for a different product and must not surface here.
    """
    constituent_index_code = str(payload.get("constituent_index_code") or "")
    future_rebalances = sorted(
        str(row["effective_date"])
        for row in payload.get("index_events", [])
        if row.get("event_type") == "REBALANCE"
        and str(row.get("index_code") or "") == constituent_index_code
        and str(row.get("effective_date") or "") > as_of_date
    )
    return future_rebalances[0] if future_rebalances else None
