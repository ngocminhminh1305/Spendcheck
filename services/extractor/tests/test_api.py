"""API tests run in-process: no separate server needs to be running."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_interactive_docs_are_available():
    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text


def test_extract_endpoint():
    response = client.post(
        "/extract",
        json={
            "text": "spent $8.90 at Kopitiam yesterday",
            "reference_datetime": "2026-10-06T18:30:00+08:00",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "amount": 8.9,
        "merchant": "Kopitiam",
        "date": "2026-10-05",
        "status": "ok",
        "missing_fields": [],
    }


def test_extract_endpoint_requires_reference_timezone():
    response = client.post(
        "/extract",
        json={
            "text": "spent $8.90 at Kopitiam yesterday",
            "reference_datetime": "2026-10-06T18:30:00",
        },
    )

    assert response.status_code == 422
