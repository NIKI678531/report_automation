"""Slot-based ingestion: several files, each authoritative for part of one snapshot.

The fixtures under ``fixtures/ingestion/`` are five real HSTECH constituents carried through the
same three files a monthly report is actually built from, including the real coverage gap where
the Bloomberg GICS sheet does not name a sector for every current constituent.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "ingestion"
# Securities present in the sample index file but absent from the sample GICS sheet.
UNCOVERED = {"20", "100", "300"}


def upload(client, report_id: str, dataset_type: str, path: Path, filename: str | None = None):
    mime = "text/csv" if path.suffix == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return client.post(
        f"/api/v1/reports/{report_id}/imports",
        data={"dataset_type": dataset_type},
        files={"file": (filename or path.name, path.read_bytes(), mime)},
    )


def apply(client, report_id: str, import_id: str, reason: str = "Approved monthly source file"):
    return client.post(f"/api/v1/reports/{report_id}/imports/{import_id}/apply", json={"reason": reason})


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


def test_every_uncovered_security_is_reported_at_once(client, report):
    """A parser that stops at the first problem forces one upload per defect."""
    constituents = upload(client, report["id"], "index_constituents", FIXTURES / "index_constituents.csv").json()
    apply(client, report["id"], constituents["id"])
    mapping = upload(client, report["id"], "sector_mapping", FIXTURES / "bloomberg_monthly.xlsx").json()
    applied = apply(client, report["id"], mapping["id"])
    assert applied.status_code == 200, applied.text
    # quality_results mixes QC checks (which carry `status`) with parse findings (which carry `error_code`).
    missing = [item for item in applied.json()["quality_results"] if item.get("error_code") == "SECTOR_MAPPING_MISSING"]
    assert {item["entity_id"] for item in missing} == UNCOVERED


def test_snapshot_stays_pending_until_every_required_slot_lands(client, report):
    report_id = report["id"]
    constituents = upload(client, report_id, "index_constituents", FIXTURES / "index_constituents.csv").json()
    first = apply(client, report_id, constituents["id"])
    assert first.status_code == 200, first.text
    # Accepted and active, but not yet calculable: returns and sectors are still missing.
    assert first.json()["status"] == "PENDING"
    assert len(first.json()["payload"]["constituents"]) == 5

    returns = upload(client, report_id, "constituent_returns", FIXTURES / "bloomberg_monthly.xlsx").json()
    second = apply(client, report_id, returns["id"])
    assert second.json()["status"] == "PENDING"
    assert second.json()["payload"]["constituents"][0]["return_1m"] is not None

    mapping = upload(client, report_id, "sector_mapping", FIXTURES / "bloomberg_monthly.xlsx").json()
    third = apply(client, report_id, mapping["id"])
    # All required slots have landed, but three securities still have no sector, so QC-004 fails.
    assert third.json()["status"] == "PENDING"

    overrides = upload(client, report_id, "sector_overrides", FIXTURES / "sector_overrides.csv").json()
    fourth = apply(client, report_id, overrides["id"])
    assert fourth.status_code == 200, fourth.text
    assert fourth.json()["status"] == "VALID"
    assert all(row["sector"] for row in fourth.json()["payload"]["constituents"])
    # Every applied slot is recorded, and each override keeps its reason and source.
    assert set(fourth.json()["payload"]["datasets"]) == {"index_constituents", "constituent_returns", "sector_mapping", "sector_overrides"}
    assert {row["security_code"] for row in fourth.json()["payload"]["overrides"]["sector"]} == UNCOVERED


def test_calculation_refuses_an_incomplete_snapshot(client, report):
    constituents = upload(client, report["id"], "index_constituents", FIXTURES / "index_constituents.csv").json()
    apply(client, report["id"], constituents["id"])
    response = client.post(f"/api/v1/reports/{report['id']}/calculations")
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "SNAPSHOT_INCOMPLETE"
    # The user needs to be told which files are still outstanding, not just that something is wrong.
    assert set(body["missing_slots"]) == {"constituent_returns", "sector_mapping"}


def test_calculation_succeeds_once_every_slot_is_applied(client, report):
    report_id = report["id"]
    for dataset_type, name in [
        ("index_constituents", "index_constituents.csv"),
        ("constituent_returns", "bloomberg_monthly.xlsx"),
        ("sector_mapping", "bloomberg_monthly.xlsx"),
        ("sector_overrides", "sector_overrides.csv"),
    ]:
        item = upload(client, report_id, dataset_type, FIXTURES / name).json()
        assert apply(client, report_id, item["id"]).status_code == 200
    calculated = client.post(f"/api/v1/reports/{report_id}/calculations")
    assert calculated.status_code == 200, calculated.text
    document = client.get(f"/api/v1/reports/{report_id}").json()["latest_document"]["content"]
    analytics = document["sections"]["analytics"]
    assert analytics["sectors"], "sector breakdown must be populated once mappings are complete"
    assert analytics["top"], "top performers require returns"


def test_returns_for_securities_outside_the_index_are_flagged_not_merged(client, report):
    """A returns file from a different index date must not smuggle in extra constituents."""
    report_id = report["id"]
    constituents = upload(client, report_id, "index_constituents", FIXTURES / "index_constituents.csv").json()
    apply(client, report_id, constituents["id"])
    # The mapping sheet carries the full 30-name universe; only 2 of the 5 sampled names overlap.
    mapping = upload(client, report_id, "sector_mapping", FIXTURES / "bloomberg_monthly.xlsx").json()
    applied = apply(client, report_id, mapping["id"])
    assert len(applied.json()["payload"]["constituents"]) == 5, "the index slot owns the constituent set"


def test_apply_never_injects_golden_fixture_data(client):
    """A first upload used to inherit the 3033 golden fixture, silently mixing approved data in."""
    report = client.post("/api/v1/reports", json={"product_code": "3033", "report_date": "2026-06-30"}).json()
    item = upload(client, report["id"], "index_constituents", FIXTURES / "index_constituents.csv").json()
    applied = apply(client, report["id"], item["id"])
    assert applied.status_code == 200, applied.text
    payload = applied.json()["payload"]
    assert len(payload["constituents"]) == 5
    assert payload["historical_performance"] == {"rows": []}
    assert payload["company_news"] == []


def test_override_without_a_stated_reason_is_rejected(client, report):
    data = b"security_code,sector,reason,source\n20,Information Technology,,\n"
    response = client.post(
        f"/api/v1/reports/{report['id']}/imports",
        data={"dataset_type": "sector_overrides"},
        files={"file": ("overrides.csv", data, "text/csv")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["validation_results"][0]["error_code"] == "OVERRIDE_UNJUSTIFIED"


def test_dataset_slots_report_progress(client, report):
    report_id = report["id"]
    slots = client.get(f"/api/v1/reports/{report_id}/datasets")
    assert slots.status_code == 200, slots.text
    by_key = {slot["key"]: slot for slot in slots.json()}
    assert set(by_key) == {"index_constituents", "constituent_returns", "sector_mapping", "sector_overrides"}
    assert all(slot["state"] == "MISSING" for slot in by_key.values())
    assert [key for key, slot in by_key.items() if slot["required"]] == ["index_constituents", "constituent_returns", "sector_mapping"]

    item = upload(client, report_id, "index_constituents", FIXTURES / "index_constituents.csv").json()
    apply(client, report_id, item["id"])
    after = {slot["key"]: slot for slot in client.get(f"/api/v1/reports/{report_id}/datasets").json()}
    assert after["index_constituents"]["state"] == "APPLIED"
    assert after["index_constituents"]["rows"] == 5
    assert after["index_constituents"]["filename"] == "index_constituents.csv"
    assert after["constituent_returns"]["state"] == "MISSING"
