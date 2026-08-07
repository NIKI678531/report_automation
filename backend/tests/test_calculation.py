from decimal import Decimal

import pytest

from app.domain.calculation import period_return, quality_checks, stable_rank


def test_period_return_uses_total_return_ratio():
    assert period_return(Decimal("100"), Decimal("112.5")) == Decimal("0.125")


def test_period_return_rejects_nonpositive_start():
    with pytest.raises(ValueError):
        period_return(Decimal("0"), Decimal("1"))


def test_rank_is_stable_by_security_code():
    rows = [{"security_code": "2", "value": 1}, {"security_code": "1", "value": 1}]
    assert [x["security_code"] for x in stable_rank(rows, "value")] == ["1", "2"]


def test_quality_checks_block_bad_weight_and_count():
    results = quality_checks({"constituents": [{"security_code": "1", "weight": 0.5, "sector": "IT"}]}, expected_constituent_count=30)
    failed = {item["check_id"] for item in results if item["status"] == "FAILED"}
    assert {"QC-002", "QC-003"}.issubset(failed)
