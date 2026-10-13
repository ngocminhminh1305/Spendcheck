"""Deterministic routing tests; real ML runs use app.inspect."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import layered
from app.main import app
from app.pipeline import extract_transaction_with_trace


REFERENCE = datetime.fromisoformat("2026-10-06T18:30:00+08:00")


def entity(text, span, name, score=0.9):
    start = text.index(span)
    return {"text": span, "start": start, "end": start + len(span),
            "candidate_field": name, "score": score}


@pytest.fixture
def models(monkeypatch):
    calls = []
    predictions = {"spacy": [], "gliner": []}
    def predict(layer, text):
        calls.append(layer)
        return predictions[layer]
    monkeypatch.setattr(layered, "extract_spacy_entities", lambda text: predict("spacy", text))
    monkeypatch.setattr(layered, "extract_gliner_entities", lambda text: predict("gliner", text))
    return calls, predictions


def test_complete_strong_rules_skip_models(models):
    result, trace = extract_transaction_with_trace("spent $8 at Kopitiam yesterday", REFERENCE)
    assert result.status == "ok"
    assert models[0] == []
    assert trace["fields"]["merchant"]["source"] == "regex"


def test_spacy_fills_merchant_and_skips_gliner(models):
    text = "Yesterday IKEA charged me $8"
    models[1]["spacy"] = [entity(text, "IKEA", "merchant")]
    result, trace = extract_transaction_with_trace(text, REFERENCE)
    assert result.merchant == "IKEA"
    assert models[0] == ["spacy"]
    assert trace["fields"]["merchant"]["source"] == "spacy"


def test_gliner_fills_after_spacy_has_no_acceptable_merchant(models):
    text = "Yesterday Kopitiam charged me $8"
    models[1]["spacy"] = [entity(text, "$8", "merchant")]
    models[1]["gliner"] = [entity(text, "Kopitiam", "merchant")]
    result, trace = extract_transaction_with_trace(text, REFERENCE)
    assert result.merchant == "Kopitiam"
    assert models[0] == ["spacy", "gliner"]
    assert trace["fields"]["merchant"]["source"] == "gliner"


@pytest.mark.parametrize("text", [
    "spent -$8 yesterday", "spent $0 yesterday", "spent $8 or $9 yesterday",
    "spent $8.999 yesterday",
])
def test_rejected_amount_cannot_be_revived(models, text):
    span = "0" if "$0" in text else "8"
    models[1]["spacy"] = [entity(text, span, "amount")]
    models[1]["gliner"] = [entity(text, span, "amount")]
    result, trace = extract_transaction_with_trace(text, REFERENCE)
    assert result.amount is None
    assert trace["fields"]["amount"]["state"] == "rejected"


def test_invalid_calendar_date_cannot_be_revived(models):
    text = "spent $8 on 2026-02-30"
    models[1]["gliner"] = [entity(text, "2026-02-30", "date")]
    result, trace = extract_transaction_with_trace(text, REFERENCE)
    assert result.date is None
    assert trace["fields"]["date"]["state"] == "rejected"


def test_nonsense_date_label_is_not_accepted(models):
    text = "Kopitiam 8"
    models[1]["gliner"] = [entity(text, text, "date")]
    result, _ = extract_transaction_with_trace(text, REFERENCE)
    assert result.date is None


def test_competing_merchants_rejected(models):
    text = "Yesterday IKEA or Muji charged me $8"
    models[1]["spacy"] = [entity(text, name, "merchant") for name in ("IKEA", "Muji")]
    result, trace = extract_transaction_with_trace(text, REFERENCE)
    assert result.merchant is None
    assert trace["fields"]["merchant"]["state"] == "rejected"
    assert models[0] == ["spacy"]


def test_low_score_remains_uncertain(models):
    text = "Yesterday Kopitiam charged me $8"
    models[1]["gliner"] = [entity(text, "Kopitiam", "merchant", 0.55)]
    result, trace = extract_transaction_with_trace(text, REFERENCE)
    assert result.merchant is None
    assert trace["fields"]["merchant"]["state"] == "uncertain"


def test_model_cannot_replace_accepted_amount(models):
    text = "Yesterday IKEA charged me $8 for 2 coffees"
    models[1]["spacy"] = [entity(text, "2", "amount"), entity(text, "IKEA", "merchant")]
    result, _ = extract_transaction_with_trace(text, REFERENCE)
    assert result.amount == 8


def test_multiple_transactions_skip_all_models(models):
    result, trace = extract_transaction_with_trace("spent $8 at Kopitiam and $5 at Chagee yesterday", REFERENCE)
    assert result.missing_fields == ["amount", "merchant", "date"]
    assert all(item["state"] == "rejected" for item in trace["fields"].values())
    assert models[0] == []


def test_conflicting_dates_rejected(models):
    result, trace = extract_transaction_with_trace("spent $8 at Kopitiam yesterday or today", REFERENCE)
    assert result.date is None
    assert trace["fields"]["date"]["state"] == "rejected"


def test_restores_literal_possessive(models):
    text = "Yesterday McDonald's charged me $8"
    models[1]["spacy"] = [entity(text, "McDonald", "merchant")]
    result, _ = extract_transaction_with_trace(text, REFERENCE)
    assert result.merchant == "McDonald's"


def test_model_failure_is_503_not_incomplete(monkeypatch):
    def fail(text):
        raise RuntimeError("model not installed")
    monkeypatch.setattr(layered, "extract_spacy_entities", fail)
    response = TestClient(app).post("/extract", json={
        "text": "Yesterday IKEA charged me $8",
        "reference_datetime": REFERENCE.isoformat(),
    })
    assert response.status_code == 503
    assert "spacy" in response.json()["detail"]


def test_trace_offsets_refer_to_cleaned_text(models):
    text = "Yesterday  IKEA\ncharged me $8"
    cleaned = "Yesterday IKEA charged me $8"
    models[1]["spacy"] = [entity(cleaned, "IKEA", "merchant")]
    _, trace = extract_transaction_with_trace(text, REFERENCE)
    assert trace["cleaned_text"] == cleaned
    assert trace["input_text"] == text


def test_uncertain_bare_number_does_not_bypass_models(models):
    text = "met 3 friends yesterday"
    models[1]["gliner"] = [entity(text, "3", "amount")]
    result, trace = extract_transaction_with_trace(text, REFERENCE)
    assert result.amount is None
    assert models[0] == ["spacy", "gliner"]
    assert trace["fields"]["amount"]["state"] == "uncertain"
