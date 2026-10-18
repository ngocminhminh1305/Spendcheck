"""Regression coverage against the submitted evaluation evidence."""

from scripts.verify_predictions import verify_predictions


def test_saved_evaluation_predictions():
    """Current paths and assets reproduce all 218 saved evaluation predictions."""
    result = verify_predictions()
    assert result["cases"] == 218
    assert result["maximum_probability_difference"] <= 1e-6
