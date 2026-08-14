from pathlib import Path


USER_HSTECH = Path("C:/Users/nikili/OneDrive - csopasset.com/Documents/HSTECH_eod_con_20260630 (1).csv")


def _create_report(client, product_code: str):
    response = client.post("/api/v1/reports", json={"product_code": product_code, "report_date": "2026-06-30"})
    assert response.status_code == 201, response.text
    return response.json()


def _master() -> bytes:
    return (
        "taxonomy,version,level,code,parent_code,name_en,name_zh_hant,valid_from,valid_to,source,source_record_key\n"
        "HSICS,HSICS-2026-112,INDUSTRY,23,,Consumer Discretionary,,2026-01-01,2026-12-31,Official,industry-23\n"
        "HSICS,HSICS-2026-112,INDUSTRY,70,,Information Technology,,2026-01-01,2026-12-31,Official,industry-70\n"
    ).encode()


def test_user_hstech_file_is_detected_as_30_validated_constituents(client):
    assert USER_HSTECH.exists(), "Acceptance fixture is missing from the user-provided path"
    report = _create_report(client, "3033")
    response = client.post(
        f"/api/v1/reports/{report['id']}/import-batches",
        files=[("files", (USER_HSTECH.name, USER_HSTECH.read_bytes(), "text/csv"))],
    )

    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["status"] == "PARTIAL_READY"
    assert batch["coverage"]["identity"]["state"] == "READY"
    assert batch["coverage"]["returns"]["state"] == "MISSING"
    assert batch["files"][0]["detected_type"] == "index_constituents"
    assert batch["files"][0]["row_count"] == 30
    assert batch["files"][0]["errors"] == []


def test_identity_only_can_save_weight_analytics_then_returns_can_complete_it(client):
    imported = client.post(
        "/api/v1/industry-master/import",
        files={"file": ("hsics.csv", _master(), "text/csv")},
        headers={"X-User-Role": "ADMIN"},
    )
    assert imported.status_code == 201, imported.text
    report = _create_report(client, "TEST")
    identity = (
        '"Prod Dt","Tradate","Idx Cde","Lcal Cde","Stk Name_E","Stk Name_TC","Cls Price","Lcal Ccy","Pct Idx Wgt","Industry","Sector"\n'
        '"20260630","20260630","TESTIDX","1","Alpha","","10","HKD","60","70","7020"\n'
        '"20260630","20260630","TESTIDX","2","Beta","","20","HKD","40","23","2320"\n'
    ).encode()
    staged_identity = client.post(
        f"/api/v1/reports/{report['id']}/import-batches",
        files=[("files", ("test-index.csv", identity, "text/csv"))],
    )
    assert staged_identity.status_code == 201, staged_identity.text
    identity_batch = staged_identity.json()
    assert identity_batch["status"] == "PARTIAL_READY"
    assert identity_batch["requires_reason"] is False
    assert identity_batch["coverage"]["returns"]["state"] == "MISSING"
    assert all(row["return_1m"] is None for row in identity_batch["merge_preview"]["rows"])

    partial = client.post(
        f"/api/v1/reports/{report['id']}/import-batches/{identity_batch['id']}/apply",
        json={"version": report["version"]},
    )
    assert partial.status_code == 200, partial.text
    partial_payload = partial.json()["payload"]
    assert all("return_1m" not in row for row in partial_payload["constituents"])
    assert [row["security_code"] for row in partial_payload["analytics"]["top10"]] == ["1", "2"]
    assert [row["code"] for row in partial_payload["analytics"]["sectors"]] == ["70", "23"]
    assert partial_payload["analytics"]["top"] == []
    assert partial_payload["analytics"]["bottom"] == []
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    assert detail["latest_document"]["content"]["sections"]["analytics"]["top10"][0]["security_code"] == "1"
    preview = client.post(f"/api/v1/reports/{report['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert "Alpha" in preview.text
    assert "Beta" in preview.text
    assert preview.text.count(">N/A<") >= 8

    returns = (
        "security_code,name_en,period_end,period_start_1m,return_1m,period_start_3m,return_3m,period_start_6m,return_6m,period_start_ytd,return_ytd,source\n"
        "1,Alpha,2026-06-30,2026-05-29,10,2026-03-31,11,2025-12-31,12,2025-12-31,13,Official\n"
        "2,Beta,2026-06-30,2026-05-29,-5,2026-03-31,-4,2025-12-31,-3,2025-12-31,-2,Official\n"
    ).encode()
    staged_returns = client.post(
        f"/api/v1/reports/{report['id']}/import-batches",
        files=[("files", ("returns.csv", returns, "text/csv"))],
    )
    assert staged_returns.status_code == 201, staged_returns.text
    returns_batch = staged_returns.json()
    assert returns_batch["status"] == "READY"
    assert returns_batch["requires_reason"] is False
    assert returns_batch["coverage"]["identity"]["source"] == "ACTIVE_SNAPSHOT"
    assert [row["security_code"] for row in returns_batch["merge_preview"]["rows"]] == ["1", "2"]

    completed = client.post(
        f"/api/v1/reports/{report['id']}/import-batches/{returns_batch['id']}/apply",
        json={"version": detail["version"]},
    )
    assert completed.status_code == 200, completed.text
    completed_payload = completed.json()["payload"]
    assert [row["return_1m"] for row in completed_payload["constituents"]] == ["0.1", "-0.05"]
    assert [row["security_code"] for row in completed_payload["analytics"]["top"]] == ["1", "2"]


def test_split_files_plus_unknown_apply_as_one_snapshot(client):
    imported = client.post(
        "/api/v1/industry-master/import",
        files={"file": ("hsics.csv", _master(), "text/csv")},
        headers={"X-User-Role": "ADMIN"},
    )
    assert imported.status_code == 201, imported.text
    report = _create_report(client, "TEST")
    identity = (
        '"Prod Dt","Tradate","Idx Cde","Lcal Cde","Stk Name_E","Stk Name_TC","Cls Price","Lcal Ccy","Pct Idx Wgt","Industry","Sector"\n'
        '"20260630","20260630","TESTIDX","1","Alpha","","10","HKD","50","70","7020"\n'
        '"20260630","20260630","TESTIDX","2","Beta","","20","HKD","50","23","2320"\n'
    ).encode()
    returns = (
        "security_code,name_en,period_end,period_start_1m,return_1m,period_start_3m,return_3m,period_start_6m,return_6m,period_start_ytd,return_ytd,source\n"
        "1,Alpha,2026-06-30,2026-05-29,10,2026-03-31,11,2025-12-31,12,2025-12-31,13,Official\n"
        "2,Beta,2026-06-30,2026-05-29,-5,2026-03-31,-4,2025-12-31,-3,2025-12-31,-2,Official\n"
    ).encode()
    before = client.get(f"/api/v1/reports/{report['id']}/snapshots").json()
    staged = client.post(
        f"/api/v1/reports/{report['id']}/import-batches",
        files=[
            ("files", ("test-index.csv", identity, "text/csv")),
            ("files", ("returns.csv", returns, "text/csv")),
            ("files", ("readme.txt", b"not a dataset", "text/plain")),
        ],
    )
    assert staged.status_code == 201, staged.text
    batch = staged.json()
    assert batch["status"] == "READY"
    assert next(item for item in batch["files"] if item["filename"] == "readme.txt")["status"] == "UNSUPPORTED"
    preview = batch["merge_preview"]
    assert preview["report_month"] == "2026-06"
    assert preview["as_of_date"] == "2026-06-30"
    assert [row["security_code"] for row in preview["rows"]] == ["1", "2"]
    assert preview["rows"][0] == {
        "security_code": "1",
        "name_en": "Alpha",
        "name_zh_hant": "",
        "close_price": "10",
        "currency": "HKD",
        "weight": "0.5",
        "return_1m": "0.1",
        "return_3m": "0.11",
        "return_6m": "0.12",
        "return_ytd": "0.13",
    }
    assert preview["unmatched_identity_codes"] == []
    assert preview["unmatched_return_codes"] == []

    applied = client.post(
        f"/api/v1/reports/{report['id']}/import-batches/{batch['id']}/apply",
        json={"version": report["version"]},
    )
    assert applied.status_code == 200, applied.text
    after = client.get(f"/api/v1/reports/{report['id']}/snapshots").json()
    assert len(after) == len(before) + 1
    assert len(applied.json()["payload"]["constituents"]) == 2
    assert all(row.get("return_1m") is not None for row in applied.json()["payload"]["constituents"])
    assert applied.json()["payload"]["return_periods"]["end"] == "2026-06-30"
    analytics = applied.json()["payload"]["analytics"]
    assert [row["security_code"] for row in analytics["top10"]] == ["1", "2"]
    assert [row["code"] for row in analytics["sectors"]] == ["23", "70"]
    assert analytics["portfolio"] == [{"label": "Number of holdings", "value": "2"}]
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    assert detail["latest_document"]["content"]["sections"]["analytics"] == analytics


def test_batch_rejects_duplicate_logical_sources(client):
    report = _create_report(client, "TEST")
    canonical_header = (
        "index_code,as_of_date,security_code,ticker,name_en,name_zh_hant,close_price,currency,weight_pct,source_industry_code,period_end,period_start_1m,return_1m_pct,return_1m_missing_reason,period_start_3m,return_3m_pct,return_3m_missing_reason,period_start_6m,return_6m_pct,return_6m_missing_reason,period_start_ytd,return_ytd_pct,return_ytd_missing_reason,constituent_source,return_source\n"
    )
    row = "TESTIDX,2026-06-30,1,0001.HK,Alpha,,10,HKD,100,70,2026-06-30,2026-05-29,1,,2026-03-31,1,,2025-12-31,1,,2025-12-31,1,,Official,Official\n"
    staged = client.post(
        f"/api/v1/reports/{report['id']}/import-batches",
        files=[
            ("files", ("one.csv", (canonical_header + row).encode(), "text/csv")),
            ("files", ("two.csv", (canonical_header + row).encode(), "text/csv")),
        ],
    )
    assert staged.status_code == 201, staged.text
    assert staged.json()["status"] == "BLOCKED"
    assert any(item["error_code"] == "BATCH_DUPLICATE_SOURCE" for item in staged.json()["errors"])
