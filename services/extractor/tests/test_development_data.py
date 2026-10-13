"""Check label consistency independently of the current extractor."""

import json
from pathlib import Path

import pytest

from app.schemas import ExtractRequest, ExtractResponse


CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "data/synthetic/development.json").read_text()
)


def test_case_ids_are_unique():
    assert len({case["id"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_expected_labels_are_consistent(case):
    ExtractRequest.model_validate(case)
    result = ExtractResponse.model_validate(case["expected"])
    missing = [
        field for field in ("amount", "merchant", "date")
        if getattr(result, field) is None
    ]
    assert result.missing_fields == missing
    assert result.status == ("incomplete" if missing else "ok")
    if result.amount is not None:
        assert result.amount > 0
