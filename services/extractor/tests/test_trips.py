"""Spendcheck integration change: ride entries such as "grab to school 14.60".

Rules only (use_models=False), so no model weights are needed.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.extractor import extract_merchant, extract_trip_provider
from app.pipeline import extract_transaction

REFERENCE = datetime(2026, 10, 16, 12, 0, tzinfo=timezone(timedelta(hours=8)))


@pytest.mark.parametrize("text, merchant, amount", [
    ("grab to school 14.60", "grab", 14.6),
    ("taxi to airport 30", "taxi", 30.0),
    ("Gojek from Changi 25.40", "Gojek", 25.4),
    ("took a grab to NUS 12.30", "grab", 12.3),
    ("bus to work 1.80", "bus", 1.8),
])
def test_ride_provider_is_the_merchant(text, merchant, amount):
    result = extract_transaction(text, REFERENCE, use_models=False)
    assert (result.merchant, result.amount) == (merchant, amount)


def test_ride_with_date():
    result = extract_transaction("grab to school 14.60 yesterday", REFERENCE, use_models=False)
    assert (result.merchant, result.amount, result.date) == ("grab", 14.6, date(2026, 10, 15))


@pytest.mark.parametrize("text", [
    "spent $8.90 at Kopitiam yesterday",   # "at" marker, not a ride
    "paid $20 to Kopitiam",                # "to" still marks a merchant when no ride word leads
    "grab food 15",                        # food delivery is a compact entry, not a trip
])
def test_non_rides_are_unchanged(text):
    assert extract_trip_provider(text) is None


def test_to_marker_still_finds_merchants():
    assert extract_merchant("paid $20 to Kopitiam") == "Kopitiam"
