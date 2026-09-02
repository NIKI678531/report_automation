from pathlib import Path

import pytest

from app.domain.industry import normalize_hsics_code, parse_industry_master_csv


FIXTURE = Path(__file__).parent / "fixtures" / "ingestion" / "index_constituents.csv"


def master_csv(version: str = "HSICS-2026-112", valid_from: str = "2026-01-01", valid_to: str = "2026-09-06") -> bytes:
    return (
        "taxonomy,version,level,code,parent_code,name_en,name_zh_hant,valid_from,valid_to,source,source_record_key\n"
        f"HSICS,{version},INDUSTRY,23,,Consumer Discretionary,非必需性消費,{valid_from},{valid_to},Official,industry-23\n"
        f"HSICS,{version},INDUSTRY,28,,Healthcare,醫療保健,{valid_from},{valid_to},Official,industry-28\n"
        f"HSICS,{version},INDUSTRY,70,,Information Technology,資訊科技,{valid_from},{valid_to},Official,industry-70\n"
    ).encode()


def test_hsics_codes_restore_level_width_and_validate_hierarchy():
    assert normalize_hsics_code(0, "INDUSTRY") == "00"
    assert normalize_hsics_code(10, "SECTOR") == "0010"
    assert normalize_hsics_code(10, "SUBSECTOR") == "000010"
    invalid = master_csv() + b"HSICS,HSICS-2026-112,SECTOR,7010,23,Bad,Bad,2026-01-01,2026-09-06,Official,bad\n"
    with pytest.raises(ValueError, match="parent_code"):
        parse_industry_master_csv(invalid)


def test_imported_effective_hsics_maps_snapshot_source_codes(client):
    imported = client.post(
        "/api/v1/industry-master/import",
        files={"file": ("hsics.csv", master_csv(), "text/csv")},
        headers={"X-User-Role": "ADMIN"},
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["created"] == 3
    report = client.post("/api/v1/reports", json={"product_code": "SLOT", "report_date": "2026-06-30"}).json()
    uploaded = client.post(
        f"/api/v1/reports/{report['id']}/imports",
        data={"dataset_type": "index_constituents"},
        files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "text/csv")},
    ).json()
    applied = client.post(
        f"/api/v1/reports/{report['id']}/imports/{uploaded['id']}/apply",
        json={"reason": "Approved report-date HSICS source"},
    )
    assert applied.status_code == 200, applied.text
    rows = applied.json()["payload"]["constituents"]
    assert {row["effective_industry_code"] for row in rows} == {"23", "28", "70"}
    assert all(row["industry_taxonomy_version"] == "HSICS-2026-112" for row in rows)
    assert applied.json()["payload"]["industry_master"]["record_count"] == 3