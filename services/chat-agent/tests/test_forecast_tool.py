"""Unit tests for the get_forecast tool's contract with Module 3 (no network or database)."""

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.tools.forecast_tool import get_forecast, load_inputs


class FakeConn:
    """Answers the two queries load_inputs makes."""

    def execute(self, sql, params):
        if "FROM transactions" in sql:
            rows = [(date(2026, 9, 3), Decimal("12.50"), "Kopitiam", "Food & Drink"),
                    (date(2026, 10, 2), Decimal("30.00"), "Grab", "Transport")]
            return SimpleNamespace(fetchall=lambda: rows)
        return SimpleNamespace(fetchone=lambda: (Decimal("900.00"),))


class ForecastTool(unittest.TestCase):
    def test_load_inputs(self):
        txns, budget = load_inputs(FakeConn(), date(2026, 10, 13))
        self.assertEqual(txns[0], {"date": "2026-09-03", "amount": 12.5, "merchant": "Kopitiam", "category": "Food & Drink"})
        self.assertEqual(budget, 900.0)

    def test_request_matches_module3_api(self):
        reply = SimpleNamespace(raise_for_status=lambda: None,
                                json=lambda: {"forecast_total": 1050.0, "risk": {"alert": True}})
        with patch("app.tools.forecast_tool.httpx.post", return_value=reply) as post:
            out = get_forecast("http://forecaster:8000", [{"date": "2026-10-02", "amount": 30.0}],
                               date(2026, 10, 13), 900.0, request_id="req-9")
        url, kwargs = post.call_args.args[0], post.call_args.kwargs
        self.assertEqual(url, "http://forecaster:8000/forecast")
        self.assertEqual(kwargs["json"], {"transactions": [{"date": "2026-10-02", "amount": 30.0}],
                                          "as_of": "2026-10-13", "budget": 900.0})
        self.assertEqual(kwargs["headers"], {"X-Request-ID": "req-9"})
        self.assertEqual((out["forecast_total"], out["budget"]), (1050.0, 900.0))


if __name__ == "__main__":
    unittest.main()
