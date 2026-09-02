import logging

from fastapi.testclient import TestClient

from app.main import create_app


def test_unexpected_error_is_correlated_with_request_id(caplog):
    app = create_app()

    @app.get("/__test__/unexpected-error")
    def raise_unexpected_error():
        raise RuntimeError("test failure")

    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/__test__/unexpected-error",
                headers={"X-Request-ID": "request-for-log-correlation"},
            )

    assert response.status_code == 500
    assert response.json()["request_id"] == "request-for-log-correlation"
    assert "request_id=request-for-log-correlation" in caplog.text
    assert "method=GET" in caplog.text
    assert "path=/__test__/unexpected-error" in caplog.text
    assert "RuntimeError: test failure" in caplog.text
