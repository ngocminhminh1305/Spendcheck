"""Shared paths and category definitions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CATEGORIES = (
    "Food & Drink", "Groceries", "Transport", "Shopping", "Entertainment",
    "Bills & Utilities", "Health", "Education", "Other",
)
CATEGORY_POLICY = {
    "Food & Drink": "Prepared meals, drinks, cafes, hawkers and food delivery.",
    "Groceries": "Supermarkets, convenience stores and grocery delivery; merchant default.",
    "Transport": "Public transit, rides, parking, vehicle rental and fuel; not wallet top-ups.",
    "Shopping": "Retail, marketplaces, stationery and general bookstores; merchant default.",
    "Entertainment": "Cinema, concerts, games, leisure attractions and media subscriptions.",
    "Bills & Utilities": "Phone, internet, electricity, water, gas and identified household bills.",
    "Health": "Healthcare, medicine and prescription optics; pharmacies default to Health.",
    "Education": "Tuition and courses; textbooks only when explicitly identified in the input.",
    "Other": "Identifiable expenses outside these categories, e.g. postage, haircut or donation.",
}
SEED = 42
