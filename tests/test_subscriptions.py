"""Subscription phrasing, including the user's reported Quizlet example."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import layered
from app.main import app
from app.pipeline import extract_transaction_with_trace


REFERENCE = datetime.fromisoformat("2026-10-09T18:30:00+08:00")


@pytest.mark.parametrize(("text", "merchant", "amount", "date"), [
    ("subscribe quizlet premium today 88 dollars", "quizlet", 88, "2026-10-09"),
    ("subscribed to Spotify Premium yesterday for $12", "Spotify", 12, "2026-10-08"),
    ("subscribe to YouTube Music today $10", "YouTube Music", 10, "2026-10-09"),
    ("subscribing to Blue Lantern premium plan today $15", "Blue Lantern", 15, "2026-10-09"),
    ("paid $8 at Premium Coffee today", "Premium Coffee", 8, "2026-10-09"),
])
def test_subscription_and_name_preservation(monkeypatch, text, merchant, amount, date):
    def unexpected_model(text):
        pytest.fail("Explicit provider pattern should not need a model")
    monkeypatch.setattr(layered, "extract_spacy_entities", unexpected_model)
    monkeypatch.setattr(layered, "extract_gliner_entities", unexpected_model)
    result, trace = extract_transaction_with_trace(text, REFERENCE)
    assert result.model_dump(mode="json") == {
        "amount": amount, "merchant": merchant, "date": date,
        "status": "ok", "missing_fields": [],
    }
    assert trace["fields"]["merchant"]["source"] == "regex"


def test_premium_alone_is_not_a_provider_even_if_model_claims_it(monkeypatch):
    text = "subscribe premium today 88 dollars"
    def predict(text):
        return [{"text": "premium", "candidate_field": "merchant", "start": 10, "end": 17, "score": 0.99}]
    monkeypatch.setattr(layered, "extract_spacy_entities", predict)
    monkeypatch.setattr(layered, "extract_gliner_entities", predict)
    result, _ = extract_transaction_with_trace(text, REFERENCE)
    assert result.merchant is None
    assert result.missing_fields == ["merchant"]


def test_quizlet_regression_through_api():
    response = TestClient(app).post("/extract", json={
        "text": "subscribe quizlet premium today 88 dollars",
        "reference_datetime": REFERENCE.isoformat(),
    })
    assert response.status_code == 200
    assert response.json() == {
        "amount": 88, "merchant": "quizlet", "date": "2026-10-09",
        "status": "ok", "missing_fields": [],
    }
