"""Test the standalone public HTTP contract and startup failures."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_prediction_and_docs(model_directory):
    """A fresh service loads its own artifact and exposes documented predictions."""
    with TestClient(create_app(model_directory)) as client:
        assert client.get("/health").json() == {
            "status": "ready", "model_version": "test", "data_status": "test fixture"}
        response = client.post("/classify", json={"merchant": "medical clinic medicine"})
        assert response.status_code == 200
        assert response.json()["category"] == "Health"
        assert response.json()["source"] == "model"
        assert "needs_review" not in response.json()
        assert client.get("/docs").status_code == 200
        assert "/classify" in client.get("/openapi.json").json()["paths"]


@pytest.mark.parametrize("body", [{}, {"merchant": None}, {"merchant": ""}, {"merchant": " \t\n"},
                                       {"merchant": "x" * 501}, {"merchant": 42},
                                       {"merchant": "clinic", "amount": 2}])
def test_invalid_inputs(body, model_directory):
    """The API rejects incomplete, oversized and unsupported request fields."""
    with TestClient(create_app(model_directory)) as client:
        assert client.post("/classify", json=body).status_code == 422


def test_review_response(model_directory):
    """A narrowly ambiguous bare name returns an explicit validation error."""
    with TestClient(create_app(model_directory)) as client:
        response = client.post("/classify", json={"merchant": "Grab"})
        assert response.status_code == 422
        assert "ambiguous_merchant" in response.json()["detail"]


def test_startup_fails_without_model(tmp_path):
    """An unavailable model cannot produce a misleading successful health response."""
    with pytest.raises(RuntimeError, match="Cannot load classifier"):
        with TestClient(create_app(tmp_path / "missing")):
            pytest.fail("Startup should fail before accepting requests")
