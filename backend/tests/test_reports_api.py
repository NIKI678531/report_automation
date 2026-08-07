def create_report(client):
    response = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}, headers={"X-Request-ID": "test-create"})
    assert response.status_code == 201, response.text
    return response.json()


def test_report_golden_lifecycle_and_preview(client):
    import pypdfium2 as pdfium
    report = create_report(client)
    snapshot = client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE", "mapping_version": "hstech-v1"},
    )
    assert snapshot.status_code == 201, snapshot.text
    assert snapshot.json()["status"] == "VALID"
    assert len(snapshot.json()["payload"]["constituents"]) == 30
    assert all(item["status"] == "PASSED" for item in snapshot.json()["quality_results"])

    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    assert detail["active_snapshot_id"]
    assert detail["latest_document"]["version"] == 2

    preview = client.post(f"/api/v1/reports/{report['id']}/preview")
    assert preview.status_code == 200
    assert preview.text.count('class="report-page"') == 4
    assert "The Performance of HSTECH Constituents" in preview.text

    finalized = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": 2})
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "FINALIZED"

    rendered = client.post(
        f"/api/v1/reports/{report['id']}/renders",
        json={"formats": ["html", "pdf", "docx"]},
        headers={"Idempotency-Key": "golden-render"},
    )
    assert rendered.status_code == 202, rendered.text
    assert [job["status"] for job in rendered.json()] == ["SUCCEEDED", "SUCCEEDED", "SUCCEEDED"]
    for job in rendered.json():
        signed = client.get(f"/api/v1/artifacts/{job['artifact_id']}/download")
        assert signed.status_code == 200
        assert "signature=" in signed.json()["download_url"]
        download = client.get(signed.json()["download_url"])
        assert download.status_code == 200
        assert len(download.content) > 1000
        if job["format"] == "pdf":
            assert len(pdfium.PdfDocument(download.content)) == 4


def test_optimistic_lock_returns_conflict(client):
    report = create_report(client)
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    content = detail["latest_document"]["content"]
    response = client.put(f"/api/v1/reports/{report['id']}/document", json={"version": 99, "content": content})
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "VERSION_CONFLICT"


def test_finalize_requires_valid_snapshot(client):
    report = create_report(client)
    response = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": 1})
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "SNAPSHOT_REQUIRED"


def test_finalized_report_creates_a_separate_revision(client):
    report = create_report(client)
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": 2})
    response = client.post(f"/api/v1/reports/{report['id']}/revisions", json={"reason": "Correct approved commentary"})
    assert response.status_code == 201, response.text
    revision = response.json()
    assert revision["id"] != report["id"]
    assert revision["parent_report_id"] == report["id"]
    assert revision["revision"] == 2
    assert revision["status"] == "DRAFT"
    assert client.get(f"/api/v1/reports/{report['id']}").json()["status"] == "FINALIZED"
