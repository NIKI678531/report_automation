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
    assert detail["status"] == "DATA_READY"
    calculated = client.post(f"/api/v1/reports/{report['id']}/calculations")
    assert calculated.status_code == 200, calculated.text
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    assert detail["active_snapshot_id"]
    assert detail["latest_document"]["version"] == calculated.json()["document_version"]
    content = detail["latest_document"]["content"]
    review = content["sections"]["month_in_review"]
    review["title"] = "June Technology Review"
    review["display_title"] = "June Technology Review"
    review["blocks"] = [
        {"block_id": "summary", "type": "rich_text", "title": "Market Context", "content": "<p>Approved market context.</p>", "x": 0, "y": 0, "w": 12, "h": 4},
        {"block_id": "outlook", "type": "outlook", "title": "Forward View", "content": "<p>Approved forward view.</p>", "x": 0, "y": 4, "w": 12, "h": 4},
    ]
    saved = client.patch(
        f"/api/v1/reports/{report['id']}/document",
        json={"version": detail["latest_document"]["version"], "content": content},
    )
    assert saved.status_code == 200, saved.text

    preview = client.post(f"/api/v1/reports/{report['id']}/preview")
    assert preview.status_code == 200
    assert preview.text.count('class="report-page"') == 4
    assert "The Performance of HSTECH Constituents" in preview.text
    assert "June Technology Review" in preview.text
    assert "Market Context" in preview.text

    finalized = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": saved.json()["version"]})
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
            pdf = pdfium.PdfDocument(download.content)
            assert len(pdf) == 4
            first_page_text = pdf[0].get_textpage().get_text_range()
            assert "June Technology Review" in first_page_text
            assert "Market Context" in first_page_text
            assert "Forward View" in first_page_text
    artifacts = client.get(f"/api/v1/reports/{report['id']}").json()["artifacts"]
    assert len({item["content_manifest_checksum"] for item in artifacts}) == 1
    assert artifacts[0]["content_manifest_checksum"]


def test_optimistic_lock_returns_conflict(client):
    report = create_report(client)
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    content = detail["latest_document"]["content"]
    response = client.patch(f"/api/v1/reports/{report['id']}/document", json={"version": 99, "content": content})
    assert response.status_code == 409
    assert response.json()["error_code"] == "VERSION_CONFLICT"


def test_finalize_requires_valid_snapshot(client):
    report = create_report(client)
    response = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": 1})
    assert response.status_code == 422
    assert response.json()["error_code"] == "SNAPSHOT_REQUIRED"


def test_finalized_report_creates_a_separate_revision(client):
    report = create_report(client)
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    calculated = client.post(f"/api/v1/reports/{report['id']}/calculations").json()
    client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": calculated["document_version"]})
    response = client.post(f"/api/v1/reports/{report['id']}/revisions", json={"reason": "Correct approved commentary"})
    assert response.status_code == 201, response.text
    revision = response.json()
    assert revision["id"] != report["id"]
    assert revision["parent_report_id"] == report["id"]
    assert revision["revision"] == 2
    assert revision["status"] == "DRAFT"
    assert client.get(f"/api/v1/reports/{report['id']}").json()["status"] == "FINALIZED"


def test_finalize_requires_calculation_module_snapshots(client):
    report = create_report(client)
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    response = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": 2})
    assert response.status_code == 422
    assert response.json()["error_code"] == "CALCULATION_REQUIRED"
    assert client.get(f"/api/v1/reports/{report['id']}").json()["status"] == "QA_BLOCKED"


def test_review_uses_the_same_calculation_gate_as_finalize(client):
    report = create_report(client)
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})

    review = client.get(f"/api/v1/reports/{report['id']}/review")

    assert review.status_code == 200, review.text
    assert review.json()["ready"] is False
    assert any(item["check_id"] == "CALCULATION_REQUIRED" for item in review.json()["blocking"])
