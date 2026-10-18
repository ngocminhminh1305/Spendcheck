"""Verify recognition, inference contracts and integrity without scoring final inputs."""

import json

import numpy as np
import pytest

from app.catalogue import MerchantCatalogue, normalise_merchant
from app.hybrid import AmbiguousMerchant, categorise_merchant, load_bundle
from app.settings import CATEGORIES
from scripts.common import read_csv, write_csv, write_json
from scripts.evaluate_hybrid import export_task, verify_release, import_task
from scripts.prepare_hybrid import DIRECTORY, CATALOGUES, check


class StubModel:
    """Force low confidence without loading or fitting a classifier."""
    classes_ = np.array(CATEGORIES)

    def predict_proba(self, merchants):
        """Return a valid diffuse distribution to demonstrate automatic fallback."""
        return np.tile([.2] + [.1] * 8, (len(merchants), 1))


def test_catalogue_exhaustive_implementation_checks():
    """Every entry and safe formatting variation must preserve identity/category."""
    for stage in ["development", "post_selection"]:
        catalogue = MerchantCatalogue.from_csv(CATALOGUES / f"catalogue_{stage}.csv")
        for row in catalogue.rows:
            for text in [row["merchant_text"], "  " + row["merchant_text"].upper() + "  ",
                         "NETS*" + row["merchant_text"], "CARD/" + row["merchant_text"]]:
                assert catalogue.match(text) == row
            assert catalogue.match(row["merchant_text"] + " unrelated business") is None


def test_collision_punctuation_and_service_separation():
    """Family membership must not collapse distinct services or unsafe punctuation."""
    rows = [dict(zip(["merchant_text", "merchant_group", "category"], [name, "grab", cat]))
            for name, cat in [("GrabFood", "Food & Drink"), ("Grab ride", "Transport"), ("GrabMart", "Groceries")]]
    catalogue = MerchantCatalogue(rows)
    for row in rows:
        result = categorise_merchant(row["merchant_text"], StubModel(), catalogue, "fixture")
        assert result["category"] == row["category"]
        assert result["confidence"] is None and result["source"] == "lookup"
    assert normalise_merchant("Disney+") != normalise_merchant("Disney")
    assert normalise_merchant("A&B") != normalise_merchant("AB")
    assert catalogue.match("GrabFood Express Unrelated") is None
    with pytest.raises(ValueError, match="collision"):
        MerchantCatalogue(rows + [{**rows[0], "merchant_text": " GRABFOOD ", "category": "Shopping"}])


def test_low_confidence_and_narrow_ambiguity():
    """Unknown and low-confidence names get predictions, not review/null categories."""
    for text in ["ABC Dental Clinic", "zzzzzzzzzzz", "Unknown Merchant", "Google", "SingPost"]:
        result = categorise_merchant(text, StubModel(), MerchantCatalogue([]), "fixture")
        assert result["category"] in CATEGORIES and result["confidence"] == .2
        assert result["source"] == "model" and "needs_review" not in result
    for text in ["Grab", " Apple ", "NETS*GRAB"]:
        with pytest.raises(AmbiguousMerchant):
            categorise_merchant(text, StubModel(), MerchantCatalogue([]), "fixture")


def test_frozen_resources_and_final_gate(tmp_path):
    """Validate only membership/hashes; never predict on B/C or reserved A inputs."""
    manifest = check()
    assert manifest["dataset_rows"] == 372
    assert [manifest["partitions"][p]["rows"] for p in ["train", "validation", "test"]] == [280, 45, 47]
    assert len(read_csv(DIRECTORY / "recognition.csv")) == 72
    assert len(read_csv(DIRECTORY / "operational.csv")) == 54
    write_json(tmp_path / "not_frozen.json", {"final_ready": False})
    for name in ["unseen", "recognition", "operational"]:
        with pytest.raises(ValueError, match="locked"):
            verify_release(tmp_path / "not_frozen.json", name)


def test_blinded_export_and_import(tmp_path):
    """Check task format, exact-once import and provenance on development data only."""
    task = tmp_path / "task"
    export_task("validation", task)
    prompt = (task / "prompt.txt").read_text()
    assert "private_answers" not in prompt and "true_category" not in prompt
    assert "new-" not in prompt and "merchant_group" not in prompt
    (tmp_path / "bad.csv").write_text("case_id,category\nE001,Invalid\n")
    with pytest.raises(ValueError, match="Missing"):
        import_task(task, tmp_path / "bad.csv", "test-only", tmp_path / "result.json")
    with pytest.raises(ValueError, match="frozen release"):
        export_task("operational", tmp_path / "final_task")
    # Synthetic oracle verifies import mechanics only; it is not a Gemini result.
    answers = json.loads((task / "manifest.json").read_text())["private_answers_do_not_paste"]
    write_csv(tmp_path / "fixture.csv", [{"case_id": i, "category": r["category"]} for i, r in answers.items()],
              ["case_id", "category"])
    report = import_task(task, tmp_path / "fixture.csv", "synthetic test fixture", tmp_path / "fixture_result.json", "2026-10-18")
    assert report["metrics"]["accuracy"] == 1 and report["run_date"] == "2026-10-18"


def test_bundle_checksums_fail_before_loading(tmp_path):
    """Corrupt catalogue or fallback metadata must stop before loading a classifier."""
    from app.model import file_hash

    model = tmp_path / "model"
    model.mkdir()
    write_json(model / "metadata.json", {"fixture": True})
    (tmp_path / "catalogue.csv").write_text("fixture")
    bundle = {"catalogue_file": "catalogue.csv", "model_directory": "model",
              "catalogue_sha256": "wrong", "fallback_metadata_sha256": file_hash(model / "metadata.json")}
    write_json(tmp_path / "bundle.json", bundle)
    with pytest.raises(RuntimeError, match="Catalogue checksum"):
        load_bundle(tmp_path / "bundle.json")
    bundle["fallback_metadata_sha256"] = "wrong"
    write_json(tmp_path / "bundle.json", bundle)
    with pytest.raises(RuntimeError, match="Fallback metadata"):
        load_bundle(tmp_path / "bundle.json")


def test_operational_report_on_fixtures_only(tmp_path, monkeypatch):
    """Exercise cohort/ablation calculations without predicting on the frozen C set."""
    import scripts.evaluate_hybrid as evaluation

    rows = [{"case_id": str(i), "merchant_text": text, "merchant_group": str(i),
             "category": category, "cohort": cohort} for i, (text, category, cohort) in enumerate([
                 ("fixture food", "Food & Drink", "known"), ("fixture clinic", "Health", "known"),
                 ("fixture new cafe", "Food & Drink", "unfamiliar"), ("fixture new clinic", "Health", "unfamiliar")])]
    catalogue = MerchantCatalogue([{k: r[k] for k in ["merchant_text", "merchant_group", "category"]}
                                   for r in rows if r["cohort"] == "known"])
    bundle = {"catalogue_version": "fixture", "catalogue_sha256": "fixture", "fallback_sha256": "fixture"}
    write_json(tmp_path / "bundle.json", bundle)
    monkeypatch.setattr(evaluation, "verify_release", lambda *args: bundle)
    monkeypatch.setattr(evaluation, "evaluation_rows", lambda *args: rows)
    monkeypatch.setattr(evaluation, "load_bundle", lambda *args: (StubModel(), catalogue, bundle))
    report = evaluation.score("operational", tmp_path / "bundle.json", tmp_path / "reports")
    assert report["ml_only"]["accuracy"] == .5
    assert report["hybrid"]["accuracy"] == .75
    assert report["lookup_only"]["accuracy"] == .5
    assert report["lookup"]["coverage"] == .5
    assert report["cohorts"]["known"]["accuracy"] == 1
    assert report["cohorts"]["unfamiliar"]["accuracy"] == .5


