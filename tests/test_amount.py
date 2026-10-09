import pytest

from app.extractor import extract_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("spent $8.90 at Kopitiam yesterday", 8.90),
        ("paid S$12.50 for lunch", 12.50),
        ("groceries cost SGD 1,234.56", 1234.56),
        ("spent 5 bucks on FairPrice", 5.0),
        ("buy 4.25 at Chagee yesterday", 4.25),
        ("kopitam 8 yesterday", 8.0),
        ("Chagee 4.25 yesterday", 4.25),
    ],
)
def test_extract_amount(text, expected):
    assert extract_amount(text) == expected


def test_missing_amount_returns_none():
    assert extract_amount("lunch at Kopitiam yesterday") is None


def test_unrelated_number_is_not_guessed_as_amount():
    assert extract_amount("met at Kopitiam on 5 October") is None


def test_year_is_not_guessed_as_amount():
    assert extract_amount("Kopitiam yesterday in 2026") is None
