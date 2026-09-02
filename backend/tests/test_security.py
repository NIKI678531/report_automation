def test_viewer_cannot_write_but_can_read(client):
    denied = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}, headers={"X-User-Role": "VIEWER"})
    assert denied.status_code == 403
    allowed = client.get("/api/v1/reports", headers={"X-User-Role": "VIEWER"})
    assert allowed.status_code == 200
    assert allowed.headers["x-content-type-options"] == "nosniff"


def test_editor_cannot_finalize(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    response = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": 1}, headers={"X-User-Role": "EDITOR"})
    assert response.status_code == 403
    assert response.json()["error_code"] == "FINALIZE_FORBIDDEN"
