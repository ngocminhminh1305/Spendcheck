"""Unit tests for parse_entry (Module 1 + Module 2 -> draft), with fake modules.

Run inside Docker:
    docker compose run --rm --no-deps -v ./services/gateway/tests:/app/tests:ro gateway python -m unittest discover -s tests -v
"""

import unittest
from datetime import datetime, timedelta, timezone

from app.entries import parse_entry

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone(timedelta(hours=8)))


class FakeServices:
    """Module 1 returns `extracted`; Module 2 answers from `categories` (missing = ambiguous)."""

    def __init__(self, extracted: dict, categories: dict):
        self.extracted, self.categories, self.classified = extracted, categories, []

    def extract(self, text, now):
        return {"amount": None, "merchant": None, "date": None, **self.extracted}

    def classify(self, merchant):
        self.classified.append(merchant)
        if merchant in self.categories:
            return self.categories[merchant]
        return {"error": "ambiguous_merchant: specify the service, e.g. GrabFood or Grab ride"}


LOOKUP = {"category": "Food & Drink", "confidence": None, "source": "lookup"}


class ParseEntry(unittest.TestCase):
    def test_complete_entry_from_the_catalogue(self):
        services = FakeServices({"amount": 4.25, "merchant": "chagee", "date": "2026-10-18"}, {"chagee": LOOKUP})
        draft = parse_entry("chagee 4.25 yesterday", NOW, services)
        self.assertEqual((draft.amount, draft.merchant, str(draft.date), draft.category), (4.25, "chagee", "2026-10-18", "Food & Drink"))
        self.assertFalse(draft.needs_review)
        self.assertEqual(draft.missing_fields, [])

    def test_missing_date_defaults_to_today(self):
        draft = parse_entry("kopi 1.80", NOW, FakeServices({"amount": 1.8, "merchant": "kopi"},
                                                           {"kopi": {"category": "Food & Drink", "confidence": 0.9, "source": "model"}}))
        self.assertEqual(str(draft.date), "2026-10-19")
        self.assertIn("today", draft.notes[0])

    def test_ride_resolves_ambiguous_grab(self):
        services = FakeServices({"amount": 14.6, "merchant": "grab"},
                                {"grab ride": {"category": "Transport", "confidence": 0.34, "source": "model"}})
        draft = parse_entry("grab to school 14.60", NOW, services)
        self.assertEqual(services.classified, ["grab", "grab ride"])
        self.assertEqual(draft.category, "Transport")
        self.assertTrue(draft.needs_review)            # model guess below 0.5: user should check it

    def test_ambiguous_without_destination_asks_the_user(self):
        services = FakeServices({"amount": 15.0, "merchant": "grab"}, {})
        draft = parse_entry("grab 15", NOW, services)
        self.assertEqual(services.classified, ["grab"])  # no retry without a destination
        self.assertIsNone(draft.category)
        self.assertIn("category", draft.missing_fields)
        self.assertTrue(draft.needs_review)

    def test_nothing_extracted_skips_the_categoriser(self):
        services = FakeServices({}, {})
        draft = parse_entry("meet friends for dinner", NOW, services)
        self.assertEqual(services.classified, [])
        self.assertEqual(draft.missing_fields, ["amount", "merchant", "category"])


if __name__ == "__main__":
    unittest.main()
