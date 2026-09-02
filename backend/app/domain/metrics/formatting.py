"""The versioned display profile. Presentation only — a display value never re-enters a calculation."""

from decimal import Decimal, ROUND_HALF_UP

# The versioned display_format_profile from the rules document §6. Values are rounded
# ROUND_HALF_UP at the presentation boundary only; `raw_value` keeps full precision and a
# `display_value` never flows back into a calculation.
DISPLAY_FORMAT_V1 = {
    "sector_weight_places": 1,
    "aum_million_places": 2,
    "turnover_million_places": 0,
}


def display_percent(value: Decimal | float | int | None, places: int = 2) -> str:
    if value is None:
        return "N/A"
    quant = Decimal(1).scaleb(-places)
    return str((Decimal(str(value)) * Decimal("100")).quantize(quant, rounding=ROUND_HALF_UP))
