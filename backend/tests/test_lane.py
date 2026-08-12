"""The TESTING lane.

``source_policy`` says where a snapshot's data came from; ``lane`` says whether it may be
distributed. The golden fixture is transcribed from an approved report rather than derived from a
source system, so it binds on TESTING — and every artifact built from it has to say so. These
tests cover the two halves of that promise: the mark cannot be avoided, and it cannot be removed.
"""
import pypdfium2 as pdfium
import pytest

from app.core.config import settings


def create_report(client, product_code: str = "3033") -> dict:
    response = client.post(
        "/api/v1/reports",
        json={"report_date": "2026-06-30", "product_code": product_code},
        headers={"X-Request-ID": "lane-test"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def bind_fixture(client, report: dict) -> dict:
    response = client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE", "mapping_version": "hstech-v1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_snapshot_creation_requires_an_explicit_source_policy(client):
    """A request that names no source used to silently get the golden fixture."""
    report = create_report(client)

    response = client.post(f"/api/v1/reports/{report['id']}/snapshots", json={})

    assert response.status_code == 422, response.text


def test_golden_fixture_is_refused_when_the_testing_lane_is_shut(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_testing_lane", False)
    report = create_report(client)

    response = client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE"},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "TESTING_LANE_DISABLED"


def test_the_fixture_lands_on_the_testing_lane_and_the_report_follows(client):
    report = create_report(client)

    snapshot = bind_fixture(client, report)

    assert snapshot["lane"] == "TESTING"
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    assert detail["lane"] == "TESTING"
    assert detail["latest_document"]["content"]["lane"] == "TESTING"


def test_an_editor_cannot_strip_the_lane_out_of_the_document(client):
    """The lane belongs to the data, so the document layer restamps it on every save."""
    report = create_report(client)
    bind_fixture(client, report)
    client.post(f"/api/v1/reports/{report['id']}/calculations")
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    content = dict(detail["latest_document"]["content"])
    content["lane"] = "PRODUCTION"

    saved = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={"version": detail["latest_document"]["version"], "content": content},
    )

    assert saved.status_code == 200, saved.text
    reloaded = client.get(f"/api/v1/reports/{report['id']}").json()
    assert reloaded["latest_document"]["content"]["lane"] == "TESTING"


def test_review_raises_lane_001_as_a_warning_not_a_block(client):
    """Testing reports must still be renderable — that is how the pipeline is regressed."""
    report = create_report(client)
    bind_fixture(client, report)
    client.post(f"/api/v1/reports/{report['id']}/calculations")

    review = client.get(f"/api/v1/reports/{report['id']}/review").json()

    lane_check = next(item for item in review["checks"] if item["check_id"] == "LANE-001")
    assert lane_check["severity"] == "WARNING"
    assert lane_check["status"] == "WARNING"
    assert lane_check["actual"] == {"lane": "TESTING", "source_policy": "GOLDEN_FIXTURE"}
    assert any(item["check_id"] == "LANE-001" for item in review["warnings"])
    assert not any(item["check_id"] == "LANE-001" for item in review["blocking"])


def test_ind_001_runs_on_the_testing_lane_too(client):
    """It used to be skipped for GOLDEN_FIXTURE, and the skip was invisible in the response."""
    report = create_report(client)
    bind_fixture(client, report)
    client.post(f"/api/v1/reports/{report['id']}/calculations")

    review = client.get(f"/api/v1/reports/{report['id']}/review").json()

    industry_check = next(item for item in review["checks"] if item["check_id"] == "IND-001")
    assert industry_check["status"] == "PASSED"


@pytest.fixture()
def finalized_testing_report(client):
    report = create_report(client)
    bind_fixture(client, report)
    calculated = client.post(f"/api/v1/reports/{report['id']}/calculations").json()
    finalized = client.post(
        f"/api/v1/reports/{report['id']}/finalize",
        json={"version": calculated["document_version"]},
    )
    assert finalized.status_code == 200, finalized.text
    return report


def test_every_rendered_format_carries_the_testing_mark(client, finalized_testing_report):
    report = finalized_testing_report

    rendered = client.post(
        f"/api/v1/reports/{report['id']}/renders",
        json={"formats": ["html", "pdf", "docx"]},
        headers={"Idempotency-Key": "lane-render"},
    )

    assert rendered.status_code == 202, rendered.text
    jobs = rendered.json()
    assert [job["status"] for job in jobs] == ["SUCCEEDED"] * 3
    for job in jobs:
        signed = client.get(f"/api/v1/artifacts/{job['artifact_id']}/download").json()
        download = client.get(signed["download_url"])
        assert download.status_code == 200
        # The name is what survives the file leaving the tool, so the lane has to be in it.
        assert f'filename="TESTING-3033_2026-06-30_v3.{job["format"]}"' in download.headers["content-disposition"]
        if job["format"] == "html":
            html = download.text
            assert html.count('class="testing-mark"') == 4
            assert html.count("TESTING DATA - NOT FOR DISTRIBUTION") == 4
        if job["format"] == "pdf":
            pdf = pdfium.PdfDocument(download.content)
            assert len(pdf) == 4
            for index in range(4):
                assert "TESTING" in pdf[index].get_textpage().get_text_bounded()


def test_the_manifest_records_the_lane(client, finalized_testing_report):
    report = finalized_testing_report
    client.post(
        f"/api/v1/reports/{report['id']}/renders",
        json={"formats": ["pdf"]},
        headers={"Idempotency-Key": "lane-manifest"},
    )

    detail = client.get(f"/api/v1/reports/{report['id']}").json()

    assert detail["artifacts"]
    assert detail["latest_document"]["content"]["lane"] == "TESTING"


def test_a_revision_of_a_testing_report_stays_on_the_testing_lane(client, finalized_testing_report):
    response = client.post(
        f"/api/v1/reports/{finalized_testing_report['id']}/revisions",
        json={"reason": "Re-check the transcribed figures"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["lane"] == "TESTING"


def test_a_production_report_carries_no_mark(client):
    """The mark is the exception, not the default: nothing is watermarked without a reason."""
    report = create_report(client)

    detail = client.get(f"/api/v1/reports/{report['id']}").json()

    assert detail["lane"] == "PRODUCTION"
    assert detail["latest_document"]["content"]["lane"] == "PRODUCTION"
    preview = client.post(f"/api/v1/reports/{report['id']}/preview")
    assert preview.status_code == 200
    assert "testing-mark" not in preview.text
    assert "NOT FOR DISTRIBUTION" not in preview.text
