"""Check the current release against saved predictions without fitting or rewriting results."""

import json

import numpy as np

from app.hybrid import categorise_merchant, load_bundle
from app.settings import ROOT
from scripts.common import read_csv
from scripts.release_hybrid import verify


def verify_predictions() -> dict:
    """Preserve saved ML probabilities, hybrid sources and recognition decisions."""
    verify()
    model, catalogue, manifest = load_bundle(ROOT / "bundles/default/manifest.json")
    _, recognition, _ = load_bundle(ROOT / "bundles/default/recognition_manifest.json")
    maximum = 0.0
    counts = {}
    paths = {"validation": ROOT / "reports/selection/minilm/validation_predictions.csv",
             "A_unseen": ROOT / "reports/evaluation/A_unseen/predictions.csv",
             "C_operational": ROOT / "reports/evaluation/C_operational/predictions.csv"}
    for name, path in paths.items():
        rows = read_csv(path)
        probabilities = model.predict_proba([r["merchant_text"] for r in rows])
        for row, probability in zip(rows, probabilities):
            category = str(model.classes_[probability.argmax()])
            expected = row["predicted_category"] if name == "validation" else row["ml_prediction"]
            if category != expected:
                raise ValueError(f"Saved ML category changed: {name}: {row['merchant_text']}")
            difference = abs(float(probability.max()) - float(row["confidence"]))
            maximum = max(maximum, difference)
            np.testing.assert_allclose(float(probability.max()), float(row["confidence"]), rtol=0, atol=1e-6)
            if name != "validation":
                result = categorise_merchant(row["merchant_text"], model, catalogue, manifest["model_version"])
                if result["category"] != row["hybrid_prediction"] or result["source"] != row["source"]:
                    raise ValueError(f"Saved hybrid output changed: {name}: {row['merchant_text']}")
        counts[name] = len(rows)
    rows = read_csv(ROOT / "reports/evaluation/B_recognition/predictions.csv")
    for row in rows:
        match = recognition.match(row["merchant_text"])
        if bool(match) != (row["matched"] == "True") or (match and match["category"] != row["predicted_category"]):
            raise ValueError(f"Saved recognition output changed: {row['case_id']}")
    counts["B_recognition"] = len(rows)
    return {"cases": sum(counts.values()), "partitions": counts,
            "maximum_probability_difference": maximum, "saved_predictions_unchanged": True}


if __name__ == "__main__":
    print(json.dumps(verify_predictions(), indent=2))
