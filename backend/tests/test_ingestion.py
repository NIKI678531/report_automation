"""Logical dataset slot ingestion and immutable snapshot composition."""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "ingestion"


def hsics_master_csv() -> bytes:
    return (
        "taxonomy,version,level,code,parent_code,name_en,name_zh_hant,valid_from,valid_to,source,source_record_key\n"
        "HSICS,HSICS-2026-112,INDUSTRY,23,,Consumer Discretionary,,2026-01-01,2026-09-06,Official,industry-23\n"
        "HSICS,HSICS-2026-112,INDUSTRY,28,,Healthcare,,2026-01-01,2026-09-06,Official,industry-28\n"
        "HSICS,HSICS-2026-112,INDUSTRY,70,,Information Technology,,2026-01-01,2026-09-06,Official,industry-70\n"
    ).encode()


def total_return_csv() -> bytes:
    rows = [
        ("2025-12-31", 100, 200),
        ("2026-03-31", 110, 220),
        ("2026-05-29", 120, 240),
        ("2026-06-30", 125, 250),
    ]
    output = "instrument_role,instrument_code,trade_date,total_return_value,series_type,currency,source\n"
    for trade_date, fund, benchmark in rows:
        output += f"FUND,SLOT.HK,{trade_date},{fund},Total Return,HKD,Official\n"
        output += f"BENCHMARK,SLOTTR,{trade_date},{benchmark},Total Return,HKD,Official\n"
    return output.encode()


def upload(client, report_id: str, dataset_type: str, path: Path, filename: str | None = None):
    mime = "text/csv" if path.suffix == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return client.post(
        f"/api/v1/reports/{report_id}/imports",
        data={"dataset_type": dataset_type},
        files={"file": (filename or path.name, path.read_bytes(), mime)},
    )


def apply(client, report_id: str, import_id: str, reason: str | None = "Monthly source replacement"):
    payload = {"reason": reason} if reason is not None else {}
    return client.post(f"/api/v1/reports/{report_id}/imports/{import_id}/apply", json=payload)


@pytest.fixture()
def report(client):
    return client.post("/api/v1/reports", json={"product_code": "SLOT", "report_date": "2026-06-30"}).json()


def test_misdirected_file_names_the_slot_it_belongs_to(client, report):
    """Uploading the Bloomberg workbook into the constituents slot is the most common mistake."""
    response = upload(client, report["id"], "index_constituents", FIXTURES / "bloomberg_monthly.xlsx")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "NEEDS_MAPPING"
    finding = body["validation_results"][0]
    assert finding["error_code"] == "MAP-001"
    # The hint has to name where the file should go, not merely that it does not fit here.
    assert "constituent_returns" in finding["fix_hint"]


def test_import_binds_the_exact_mapping_profile_and_reports_duplicate_return_group(client, report):
    response = upload(client, report["id"], "constituent_returns", FIXTURES / "bloomberg_monthly.xlsx")
    assert response.status_code == 201, response.text
    body = response.json()
    profiles = client.get("/api/v1/mapping-profiles?dataset_type=constituent_returns").json()
    assert body["mapping_profile_id"] == profiles[0]["id"]
    assert body["mapping_version"] == 1
    assert any(item["error_code"] == "IGNORED_DUPLICATE_RETURN_GROUP" for item in body["validation_results"])


def test_standard_constituent_return_csv_preserves_periods_and_explicit_percent_unit(client, report):
    data = (
        "security_code,name_en,period_end,period_start_1m,return_1m,period_start_3m,return_3m,period_start_6m,return_6m,period_start_ytd,return_ytd,source\n"
        "20,Example,2026-06-30,2026-05-29,10,2026-03-31,11,2025-12-31,12,2025-12-31,13,Official\n"
    ).encode()
    response = client.post(
        f"/api/v1/reports/{report['id']}/imports",
        data={"dataset_type": "constituent_returns"},
        files={"file": ("constituent-returns.csv", data, "text/csv")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "VALIDATED"
    assert body["payload"]["constituent_returns"][0]["return_1m"] == "0.1"
    assert body["payload"]["return_periods"]["starts"]["return_6m"] == "2025-12-31"


def test_mapping_profile_versions_are_admin_only_and_immutable(client):
    command = {
        "profile_id": "new_vendor_constituents",
        "dataset_type": "index_constituents",
        "source_family": "NEW_VENDOR",
        "selector": {"extensions": [".csv"], "required_fields": ["security_code", "weight", "close_price"]},
        "field_map": {
            "security_code": {"aliases": ["Security"]},
            "weight": {"aliases": ["Weight"]},
            "close_price": {"aliases": ["Close"]},
        },
        "unit_map": {"weight": "PERCENT"},
        "version": 1,
        "status": "APPROVED",
    }
    forbidden = client.post("/api/v1/mapping-profiles", json=command, headers={"X-User-Role": "EDITOR"})
    assert forbidden.status_code == 403
    created = client.post("/api/v1/mapping-profiles", json=command, headers={"X-User-Role": "ADMIN"})
    assert created.status_code == 201, created.text
    assert created.json()["approved_by"] == "local-user"
    duplicate = client.post("/api/v1/mapping-profiles", json=command, headers={"X-User-Role": "ADMIN"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "MAPPING_PROFILE_IMMUTABLE"


def test_first_slot_apply_needs_no_reason_but_replacing_that_slot_does(client, report):
    report_id = report["id"]
    first_import = upload(client, report_id, "index_constituents", FIXTURES / "index_constituents.csv").json()

    first_apply = apply(client, report_id, first_import["id"], reason=None)

    assert first_apply.status_code == 200, first_apply.text
    assert first_apply.json()["payload"]["datasets"]["index_constituents"]["import_id"] == first_import["id"]

    returns_import = upload(client, report_id, "constituent_returns", FIXTURES / "bloomberg_monthly.xlsx").json()
    first_returns_apply = apply(client, report_id, returns_import["id"], reason=None)

    assert first_returns_apply.status_code == 200, first_returns_apply.text
    assert first_returns_apply.json()["payload"]["datasets"]["constituent_returns"]["import_id"] == returns_import["id"]

    replacement = upload(client, report_id, "index_constituents", FIXTURES / "index_constituents.csv").json()
    assert replacement["apply_mode"] == "OVERWRITE"
    assert replacement["requires_reason"] is True
    missing_reason = apply(client, report_id, replacement["id"], reason=None)

    assert missing_reason.status_code == 422, missing_reason.text
    assert missing_reason.json()["error_code"] == "IMPORT_REASON_REQUIRED"

    replaced = apply(client, report_id, replacement["id"], reason="Corrected monthly source")
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["payload"]["datasets"]["index_constituents"]["import_id"] == replacement["id"]
    events = client.get("/api/v1/audit").json()
    replacement_audit = next(event for event in events if event["action"] == "import.applied" and event["entity_id"] == replacement["id"])
    assert replacement_audit["details"]["apply_mode"] == "OVERWRITE"
    assert replacement_audit["details"]["reason"] == "Corrected monthly source"
    assert replacement_audit["details"]["replaced_checksum"]
    assert replacement_audit["details"]["diff"] == replacement["diff"]


def test_calculation_refuses_an_incomplete_snapshot(client, report):
    constituents = upload(client, report["id"], "index_constituents", FIXTURES / "index_constituents.csv").json()
    apply(client, report["id"], constituents["id"])
    response = client.post(f"/api/v1/reports/{report['id']}/calculations")
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "SNAPSHOT_INCOMPLETE"
    # The user needs to be told which files are still outstanding, not just that something is wrong.
    assert set(body["missing_slots"]) == {
        "constituent_returns", "total_return_series", "fund_kpi_daily",
        "trading_calendar", "industry_master",
    }


def test_required_logical_slots_auto_calculate_without_golden_fixture(client):
    imported_master = client.post(
        "/api/v1/industry-master/import",
        files={"file": ("hsics.csv", hsics_master_csv(), "text/csv")},
        headers={"X-User-Role": "ADMIN"},
    )
    assert imported_master.status_code == 201, imported_master.text
    report = client.post("/api/v1/reports", json={"product_code": "SLOT", "report_date": "2026-06-30"}).json()
    report_id = report["id"]
    sources = [
        ("index_constituents", "index_constituents.csv", FIXTURES / "index_constituents.csv"),
        ("constituent_returns", "bloomberg_monthly.xlsx", FIXTURES / "bloomberg_monthly.xlsx"),
        ("total_return_series", "total-returns.csv", total_return_csv()),
        ("fund_kpi_daily", "fund-kpis.csv", b"metric_code,metric_date,value,unit,currency,source\nAUM,2026-06-30,1000,million,HKD,Official\nDAILY_TURNOVER,2026-06-29,50,million,HKD,Official\n"),
        ("trading_calendar", "calendar.csv", b"market,date,is_trading_day,source\nHK,2026-06-29,true,Official\n"),
    ]

    last_snapshot = None
    for dataset_type, filename, source in sources:
        if isinstance(source, Path):
            uploaded = upload(client, report_id, dataset_type, source).json()
        else:
            uploaded = client.post(
                f"/api/v1/reports/{report_id}/imports",
                data={"dataset_type": dataset_type},
                files={"file": (filename, source, "text/csv")},
            ).json()
        assert uploaded["status"] == "VALIDATED", uploaded
        applied = apply(client, report_id, uploaded["id"], reason=None)
        assert applied.status_code == 200, applied.text
        last_snapshot = applied.json()

    assert last_snapshot is not None
    assert last_snapshot["status"] == "VALID"
    detail = client.get(f"/api/v1/reports/{report_id}").json()
    assert detail["status"] == "EDITING"
    assert detail["latest_document"]["content"]["formula_version"] == "test-index-v1"
    assert detail["latest_document"]["content"]["sections"]["historical_performance"]["rows"]
    modules = client.get(f"/api/v1/reports/{report_id}/modules").json()
    assert {item["module_code"] for item in modules} == {
        "historical_performance", "constituents_performance", "final_analytics", "footnotes",
    }
    content = detail["latest_document"]["content"]
    content["sections"]["month_in_review"]["summary"] = "Monthly market review complete."
    content["sections"]["month_in_review"]["outlook"] = "Continue monitoring constituent fundamentals."
    saved = client.patch(
        f"/api/v1/reports/{report_id}/document",
        json={"version": detail["latest_document"]["version"], "content": content},
    )
    assert saved.status_code == 200, saved.text
    news = client.post(f"/api/v1/reports/{report_id}/news/candidates", json={
        "source_name": "Official News",
        "source_url": "https://example.test/monthly-news",
        "published_at": "2026-06-15T08:00:00Z",
        "title": "Constituent publishes monthly update",
        "summary": "The constituent published an operational update for the report month.",
        "ticker": "0020.HK",
    })
    assert news.status_code == 201, news.text
    selected = client.put(f"/api/v1/reports/{report_id}/news", json={
        "version": saved.json()["version"],
        "items": [{"news_item_id": news.json()["id"], "position": 0}],
    })
    assert selected.status_code == 200, selected.text
    review = client.get(f"/api/v1/reports/{report_id}/review")
    assert review.status_code == 200, review.text
    assert review.json()["ready"] is True, review.json()["blocking"]
    finalized = client.post(
        f"/api/v1/reports/{report_id}/finalize",
        json={"version": selected.json()["version"]},
    )
    assert finalized.status_code == 200, finalized.text
    rendered = client.post(
        f"/api/v1/reports/{report_id}/renders",
        json={"formats": ["html", "pdf", "docx"]},
        headers={"Idempotency-Key": f"slot-lifecycle-{report_id}"},
    )
    assert rendered.status_code == 202, rendered.text
    assert [job["status"] for job in rendered.json()] == ["SUCCEEDED", "SUCCEEDED", "SUCCEEDED"]
    artifacts = client.get(f"/api/v1/reports/{report_id}").json()["artifacts"]
    assert len({artifact["content_manifest_checksum"] for artifact in artifacts}) == 1
    for artifact in artifacts:
        signed = client.get(f"/api/v1/artifacts/{artifact['id']}/download").json()
        downloaded = client.get(signed["download_url"])
        assert downloaded.status_code == 200
        assert downloaded.content


def test_final_slot_rolls_back_when_automatic_calculation_fails(client):
    client.post(
        "/api/v1/industry-master/import",
        files={"file": ("hsics.csv", hsics_master_csv(), "text/csv")},
        headers={"X-User-Role": "ADMIN"},
    )
    report = client.post("/api/v1/reports", json={"product_code": "SLOT", "report_date": "2026-06-30"}).json()
    report_id = report["id"]
    incomplete_returns = (
        "instrument_role,instrument_code,trade_date,total_return_value,series_type,currency,source\n"
        "FUND,SLOT.HK,2026-03-31,100,Total Return,HKD,Official\n"
        "BENCHMARK,SLOTTR,2026-03-31,200,Total Return,HKD,Official\n"
        "FUND,SLOT.HK,2026-05-29,110,Total Return,HKD,Official\n"
        "BENCHMARK,SLOTTR,2026-05-29,220,Total Return,HKD,Official\n"
        "FUND,SLOT.HK,2026-06-30,120,Total Return,HKD,Official\n"
        "BENCHMARK,SLOTTR,2026-06-30,240,Total Return,HKD,Official\n"
    ).encode()
    sources = [
        ("index_constituents", "index.csv", (FIXTURES / "index_constituents.csv").read_bytes(), "text/csv"),
        ("constituent_returns", "returns.xlsx", (FIXTURES / "bloomberg_monthly.xlsx").read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("total_return_series", "total.csv", incomplete_returns, "text/csv"),
        ("fund_kpi_daily", "kpi.csv", b"metric_code,metric_date,value,unit,currency,source\nAUM,2026-06-30,1000,million,HKD,Official\nDAILY_TURNOVER,2026-06-29,50,million,HKD,Official\n", "text/csv"),
    ]
    for dataset_type, filename, data, mime in sources:
        uploaded = client.post(
            f"/api/v1/reports/{report_id}/imports",
            data={"dataset_type": dataset_type},
            files={"file": (filename, data, mime)},
        ).json()
        applied = client.post(f"/api/v1/reports/{report_id}/imports/{uploaded['id']}/apply", json={})
        assert applied.status_code == 200, applied.text
    before = client.get(f"/api/v1/reports/{report_id}").json()
    calendar = client.post(
        f"/api/v1/reports/{report_id}/imports",
        data={"dataset_type": "trading_calendar"},
        files={"file": ("calendar.csv", b"market,date,is_trading_day,source\nHK,2026-06-29,true,Official\n", "text/csv")},
    ).json()

    failed = client.post(f"/api/v1/reports/{report_id}/imports/{calendar['id']}/apply", json={})

    assert failed.status_code == 422, failed.text
    assert failed.json()["error_code"] == "HISTORICAL_PERIODS_INCOMPLETE"
    after = client.get(f"/api/v1/reports/{report_id}").json()
    assert after["active_snapshot_id"] == before["active_snapshot_id"]
    imports = client.get(f"/api/v1/reports/{report_id}/imports").json()
    assert next(item for item in imports if item["id"] == calendar["id"])["status"] == "VALIDATED"


def test_returns_for_securities_outside_the_index_are_flagged_not_merged(client, report):
    """A returns file from a different index date must not smuggle in extra constituents."""
    report_id = report["id"]
    constituents = upload(client, report_id, "index_constituents", FIXTURES / "index_constituents.csv").json()
    apply(client, report_id, constituents["id"])
    returns = upload(client, report_id, "constituent_returns", FIXTURES / "bloomberg_monthly.xlsx").json()
    applied = apply(client, report_id, returns["id"])
    assert len(applied.json()["payload"]["constituents"]) == 5, "the index slot owns the constituent set"


def test_apply_never_injects_golden_fixture_data(client):
    """A first upload must not inherit the 3033 golden fixture or silently mix sources."""
    report = client.post("/api/v1/reports", json={"product_code": "3033", "report_date": "2026-06-30"}).json()
    item = upload(client, report["id"], "index_constituents", FIXTURES / "index_constituents.csv").json()
    applied = apply(client, report["id"], item["id"])
    assert applied.status_code == 200, applied.text
    payload = applied.json()["payload"]
    assert len(payload["constituents"]) == 5
    assert payload["historical_performance"] == {"rows": []}
    assert payload["company_news"] == []


def test_dataset_slots_report_progress(client, report):
    report_id = report["id"]
    slots = client.get(f"/api/v1/reports/{report_id}/datasets")
    assert slots.status_code == 200, slots.text
    by_key = {slot["key"]: slot for slot in slots.json()}
    assert set(by_key) == {
        "index_constituents", "constituent_returns", "total_return_series",
        "fund_kpi_daily", "trading_calendar", "index_events", "industry_master",
    }
    assert all(slot["state"] == "MISSING" for slot in by_key.values())
    assert {key for key, slot in by_key.items() if slot["required"]} == {
        "index_constituents", "constituent_returns", "total_return_series",
        "fund_kpi_daily", "trading_calendar", "industry_master",
    }
    assert by_key["index_events"]["required"] is False

    item = upload(client, report_id, "index_constituents", FIXTURES / "index_constituents.csv").json()
    apply(client, report_id, item["id"])
    after = {slot["key"]: slot for slot in client.get(f"/api/v1/reports/{report_id}/datasets").json()}
    assert after["index_constituents"]["state"] == "APPLIED"
    assert after["index_constituents"]["rows"] == 5
    assert after["index_constituents"]["filename"] == "index_constituents.csv"
    assert after["constituent_returns"]["state"] == "MISSING"
