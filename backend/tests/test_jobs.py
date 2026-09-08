"""On-demand exports: immutable source, authorization, failures and scratch lifetime."""
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import anyio
import pytest
from sqlalchemy import select

from app.api.routes import render as routes
from app.domain.models import AuditEvent, RenderArtifact, RenderJob, ReportDocument
from app.domain.document import checksum
from app.rendering import artifacts
from app.rendering.download_response import ExportResponse
from conftest import download_report


def finalized(client):
    response = client.post("/api/v1/reports", json={"report_date": "2026-06-30"})
    assert response.status_code == 201
    report_id = response.json()["id"]
    assert client.post(f"/api/v1/reports/{report_id}/finalize", json={"version": 1}).status_code == 200
    return report_id


def test_every_download_renders_again_and_removes_files_without_artifact_rows(client, monkeypatch):
    report_id = finalized(client)
    original = routes.generate_export
    paths = []

    def track(*args):
        output = original(*args)
        paths.append(output.path)
        assert output.path.exists()
        return output

    monkeypatch.setattr(routes, "generate_export", track)
    for _ in range(2):
        response = download_report(client, report_id, "html")
        assert "<html" in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["accept-ranges"] == "none"
        assert all(not path.parent.exists() for path in paths)
    assert len(paths) == len(set(paths)) == 2
    with client.app.state.testing_sessionmaker() as db:
        assert list(db.scalars(select(RenderArtifact))) == []
        assert list(db.scalars(select(RenderJob))) == []
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "export.generated")))
        assert len(events) == 2
        assert all(event.details["document_version"] == 1 and event.details["size_bytes"] > 0 for event in events)
        assert all(len(event.details["checksum"]) == 64 for event in events)


def test_archived_finalized_report_uses_fixed_version_even_if_later_document_exists(client, monkeypatch):
    report_id = finalized(client)
    with client.app.state.testing_sessionmaker() as db:
        fixed = db.scalar(select(ReportDocument).where(ReportDocument.report_id == report_id))
        content = {**fixed.content, "should_not_export": "later document"}
        db.add(ReportDocument(report_id=report_id, version=2, content=content, checksum=checksum(content), template_version=fixed.template_version))
        db.commit()
    report = client.get(f"/api/v1/reports/{report_id}").json()
    assert client.delete(f"/api/v1/reports/{report_id}?version={report['version']}").status_code == 204
    seen = []
    original = routes.generate_export

    def track(report, document, format_name):
        seen.append(document.version)
        assert "should_not_export" not in document.content
        return original(report, document, format_name)

    monkeypatch.setattr(routes, "generate_export", track)
    download_report(client, report_id, "html")
    assert seen == [1]


def test_draft_and_archived_draft_cannot_export(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    path = f"/api/v1/reports/{report['id']}/exports/html/download"
    assert client.get(path).status_code == 422
    client.delete(f"/api/v1/reports/{report['id']}?version={report['version']}")
    assert client.get(path).status_code == 422


def test_export_failure_removes_partial_output_and_records_safe_failure(client, monkeypatch):
    report_id = finalized(client)
    paths = []

    def fail(report, document, format_name, destination):
        paths.append(destination)
        destination.write_bytes(b"partial")
        raise OSError("private internal path and credentials")

    monkeypatch.setattr(artifacts, "_render_file", fail)
    signed = client.get(f"/api/v1/reports/{report_id}/exports/html/download").json()
    response = client.get(signed["download_url"])
    assert response.status_code == 503
    assert response.json()["error_code"] == "EXPORT_FAILED"
    assert "private" not in response.text
    assert all(not path.parent.exists() for path in paths)
    events = client.get(f"/api/v1/audit?report_id={report_id}").json()
    assert any(e["action"] == "export.failed" for e in events)
    assert not any(e["action"] == "export.generated" for e in events)


@pytest.mark.parametrize("alter", ["subject", "scope", "signature", "unicode_signature", "expires", "version", "format"])
def test_export_grant_cannot_change_subject_scope_expiry_version_or_format(client, monkeypatch, alter):
    report_id = finalized(client)
    headers = {"X-User-ID": "alice", "X-User-Role": "VIEWER", "X-Product-Scope": "3033"}
    signed = client.get(f"/api/v1/reports/{report_id}/exports/html/download", headers=headers).json()["download_url"]
    url = urlsplit(signed)
    query = parse_qs(url.query)
    if alter == "subject":
        headers["X-User-ID"] = "bob"
    elif alter == "scope":
        headers["X-Product-Scope"] = "other"
    elif alter == "format":
        url = url._replace(path=url.path.replace("/html/", "/pdf/"))
    elif alter == "unicode_signature":
        query["signature"] = ["非法签名"]
    else:
        query[alter] = ["invalid" if alter == "signature" else "0" if alter == "expires" else "2"]
    monkeypatch.setattr(routes, "generate_export", lambda *_: pytest.fail("unauthorized rendering"))
    response = client.get(urlunsplit(url._replace(query=urlencode(query, doseq=True))), headers=headers)
    assert response.status_code == (404 if alter == "scope" else 409 if alter == "version" else 403)


def test_viewer_can_download_finalized_report(client):
    report_id = finalized(client)
    download_report(client, report_id, "html", headers={"X-User-Role": "VIEWER"})


def test_range_request_returns_complete_fresh_export(client):
    report_id = finalized(client)
    response = download_report(client, report_id, "html", headers={"Range": "bytes=0-2", "If-Range": '"old-export"'})
    assert "content-range" not in response.headers
    assert len(response.content) > 3
    assert "<html" in response.text


def test_corrupt_finalized_content_cannot_be_exported(client, monkeypatch):
    report_id = finalized(client)
    with client.app.state.testing_sessionmaker() as db:
        document = db.scalar(select(ReportDocument).where(ReportDocument.report_id == report_id))
        document.content = {**document.content, "corruption": True}
        db.commit()
    monkeypatch.setattr(routes, "generate_export", lambda *_: pytest.fail("corrupt content rendered"))
    response = client.get(f"/api/v1/reports/{report_id}/exports/html/download")
    assert response.status_code == 409
    assert response.json()["error_code"] == "DOCUMENT_CHECKSUM_MISMATCH"


def test_response_cleanup_runs_when_sending_fails(client):
    report_id = finalized(client)
    with client.app.state.testing_sessionmaker() as db:
        report, document = routes.export_source(db, report_id)
    output = artifacts.generate_export(report, document, "html")
    directory = output.path.parent

    async def exercise():
        async def receive():
            return {"type": "http.request", "body": b""}
        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")
        with pytest.raises(OSError, match="disconnected"):
            await ExportResponse(output)({"type": "http", "method": "GET", "headers": [], "extensions": {"http.response.pathsend": {}}}, receive, send)
    anyio.run(exercise)
    assert not directory.exists()
