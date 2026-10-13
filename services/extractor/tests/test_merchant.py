import pytest

from app.extractor import extract_merchant


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("spent $8.90 at Kopitiam yesterday", "Kopitiam"),
        ("paid S$12.50 at Toast Box today", "Toast Box"),
        ("spent 5 bucks on FairPrice this morning", "FairPrice"),
        ("paid $18 to Grab yesterday", "Grab"),
        ("buy Chagee 4.25 yesterday", "Chagee"),
        ("bought McDonald's $9.50 today", "McDonald's"),
        ("7-Eleven 3.20 yesterday", "7-Eleven"),
        ("$8.90 Kopitiam yesterday", "Kopitiam"),
        ("lunch at Kopitiam for $8.90 yesterday", "Kopitiam"),
    ],
)
def test_extract_merchant(text, expected):
    assert extract_merchant(text) == expected


def test_missing_merchant_returns_none():
    assert extract_merchant("spent $8.90 yesterday") is None


def test_date_after_on_is_not_a_merchant():
    assert extract_merchant("spent $8.90 on 05/10/2026") is None
