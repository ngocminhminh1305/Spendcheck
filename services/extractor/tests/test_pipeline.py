from datetime import datetime
from functools import partial

from app.pipeline import extract_transaction, preprocess_text

extract_transaction = partial(extract_transaction, use_models=False)


REFERENCE_DATETIME = datetime.fromisoformat("2026-10-06T18:30:00+08:00")


def test_preprocess_collapses_whitespace():
    assert preprocess_text("  spent   $8.90\n at Kopitiam  ") == "spent $8.90 at Kopitiam"


def test_complete_transaction():
    result = extract_transaction(
        "spent $8.90 at Kopitiam yesterday", REFERENCE_DATETIME
    )

    assert result.model_dump(mode="json") == {
        "amount": 8.9,
        "merchant": "Kopitiam",
        "date": "2026-10-05",
        "status": "ok",
        "missing_fields": [],
    }


def test_incomplete_transaction():
    result = extract_transaction("lunch yesterday", REFERENCE_DATETIME)

    assert result.model_dump(mode="json") == {
        "amount": None,
        "merchant": None,
        "date": "2026-10-05",
        "status": "incomplete",
        "missing_fields": ["amount", "merchant"],
    }


def test_non_positive_amount_is_invalid():
    result = extract_transaction("spent $0 at Kopitiam today", REFERENCE_DATETIME)

    assert result.amount is None
    assert result.status == "incomplete"
    assert result.missing_fields == ["amount"]


def test_messy_input_with_date_typo():
    result = extract_transaction("kopitam 8 yesterdat", REFERENCE_DATETIME)

    assert result.model_dump(mode="json") == {
        "amount": 8.0,
        "merchant": "kopitam",
        "date": "2026-10-05",
        "status": "ok",
        "missing_fields": [],
    }
