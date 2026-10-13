from datetime import date, datetime

import pytest

from app.extractor import extract_date


REFERENCE_DATETIME = datetime.fromisoformat("2026-10-06T18:30:00+08:00")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("spent $8.90 at Kopitiam yesterday", date(2026, 10, 5)),
        ("coffee today", date(2026, 10, 6)),
        ("dinner two days ago", date(2026, 10, 4)),
        ("buy 4.25 at Chagee last Friday", date(2026, 10, 2)),
        ("paid $12 on 5 October 2026", date(2026, 10, 5)),
        ("lunch on 05/10/2026", date(2026, 10, 5)),
        ("lunch on 2026-10-05", date(2026, 10, 5)),
    ],
)
def test_extract_date(text, expected):
    assert extract_date(text, REFERENCE_DATETIME) == expected


def test_missing_date_returns_none():
    assert extract_date("spent $8.90 at Kopitiam", REFERENCE_DATETIME) is None


def test_amount_is_not_treated_as_date():
    assert extract_date("spent $8.90 at Kopitiam", REFERENCE_DATETIME) is None
