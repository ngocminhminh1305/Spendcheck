"""Raw classification metrics and training-only keyword baseline."""
from collections import defaultdict
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from app.cleaning import clean_merchant
from app.settings import CATEGORIES

KEYWORDS = {
    "Food & Drink": {"cafe", "coffee", "tea", "restaurant", "hawker", "food", "meal", "kopi", "ramen"},
    "Groceries": {"supermarket", "grocery", "grocer", "groceries", "mart"},
    "Transport": {"taxi", "ride", "rides", "transit", "mrt", "bus", "parking", "fuel", "carpark"},
    "Shopping": {"retail", "shopping", "bookstore", "stationery", "clothing"},
    "Entertainment": {"cinema", "concert", "games", "theatres", "karaoke", "ktv", "zoo"},
    "Bills & Utilities": {"utilities", "electricity", "broadband", "mobile", "bill", "utility", "gas"},
    "Health": {"clinic", "hospital", "medical", "dental", "pharmacy", "medicine", "polyclinic"},
    "Education": {"tuition", "course", "textbook", "textbooks", "university", "lesson", "courses"},
    "Other": {"postage", "haircut", "salon", "laundry", "donation", "storage", "notary", "passport"},
}

def keyword_predictions(training: list[dict], merchants: list[str]) -> list[str]:
    """Use unambiguous training-name matches, then policy keywords, then Other."""
    lookup = defaultdict(set)
    for row in training:
        lookup[clean_merchant(row["merchant_text"])].add(row["category"])
    predictions = []
    for merchant in merchants:
        text = clean_merchant(merchant)
        exact = lookup.get(text, set())
        if len(exact) == 1:
            predictions.append(next(iter(exact)))
            continue
        tokens = set(text.split())
        matches = [(len(tokens & words), category) for category, words in KEYWORDS.items()]
        maximum = max(score for score, _ in matches)
        winners = [category for score, category in matches if score == maximum]
        predictions.append(winners[0] if maximum > 0 and len(winners) == 1 else "Other")
    return predictions

def score_predictions(expected: list[str], predicted: list[str]) -> dict:
    """Score all nine categories, including zero-support or missing prediction classes."""
    return {
        "rows": len(expected), "accuracy": float(accuracy_score(expected, predicted)),
        "macro_f1": float(f1_score(expected, predicted, labels=list(CATEGORIES), average="macro", zero_division=0)),
        "per_category": classification_report(expected, predicted, labels=list(CATEGORIES),
                                               output_dict=True, zero_division=0),
        "confusion_matrix": confusion_matrix(expected, predicted, labels=list(CATEGORIES)).tolist(),
        "confusion_matrix_labels": list(CATEGORIES),
    }
