"""Regression cases for abstention, rather than guessing a complete result."""

import json
from datetime import datetime
from pathlib import Path
from functools import partial

import pytest

from app.extractor import extract_amount
from app.pipeline import extract_transaction, preprocess_text

# Baseline regressions deliberately isolate rules; ML is tested separately.
extract_transaction = partial(extract_transaction, use_models=False)


REFERENCE = datetime.fromisoformat("2026-10-06T18:30:00+08:00")
CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "data/synthetic/development.json").read_text()
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_development_extraction(case):
    result = extract_transaction(
        case["text"], datetime.fromisoformat(case["reference_datetime"])
    )
    assert result.model_dump(mode="json") == case["expected"]


@pytest.mark.parametrize("text", [
    "spent $8 or $9 yesterday",
    "spent $8 or 9 yesterday",
    "spent -$8 yesterday",
    "spent SGD -8 yesterday",
    "spent $8.999 yesterday",
    "spent $1,23 yesterday",
    "bought 2 coffees yesterday",
    "Kopitiam 2 days ago",
])
def test_unsupported_or_non_money_numbers(text):
    assert extract_amount(text) is None


def test_preprocessing_preserves_similar_merchant_names():
    assert preprocess_text("spent $8 at Augustus today") == "spent $8 at Augustus today"


def test_single_purchase_with_quantity():
    result = extract_transaction("bought 2 coffees for $8 at Kopitiam yesterday", REFERENCE)
    assert result.amount == 8
    assert result.merchant == "Kopitiam"
