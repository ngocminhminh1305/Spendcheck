"""Check cleaning, artifact portability and review decisions with real features."""

import json

import numpy as np
import pytest

from app.cleaning import clean_merchant
from app.model import load_model


def test_cleaning_preserves_service_meaning():
    """Payment-prefix and separator cleanup must not merge food delivery with rides."""
    assert clean_merchant("  ＮＥＴＳ*KOPITIAM / SG ") == "kopitiam sg"
    assert clean_merchant("CARD*GRAB*GRABFOOD SG") == "grab grabfood sg"
    assert clean_merchant("GRAB* RIDES SG") != clean_merchant("GRAB* GRABFOOD SG")
    assert clean_merchant("NETS Healthcare") == "nets healthcare"


def test_saved_pipeline_and_external_working_directory(model_directory, sample_pipeline, monkeypatch, tmp_path):
    """Serialized preprocessing and predictions survive reloads and a changed cwd."""
    monkeypatch.chdir(tmp_path.parent)
    loaded, _ = load_model(model_directory)
    merchants = ["CARD*medical clinic medicine", "cafe tea meal", "taxi bus ride"]
    np.testing.assert_allclose(loaded.predict_proba(merchants), sample_pipeline.predict_proba(merchants))


def test_missing_and_incompatible_artifacts(model_directory, tmp_path):
    """Missing files, version drift and model replacement fail with actionable errors."""
    with pytest.raises(RuntimeError, match="Cannot load classifier"):
        load_model(tmp_path / "missing")
    path = model_directory / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata["sklearn_version"] = "0.0"
    path.write_text(json.dumps(metadata))
    with pytest.raises(RuntimeError, match="version differs"):
        load_model(model_directory)


def test_corrupt_model_checksum(model_directory):
    """Corrupted or replaced artifact bytes are rejected before deserialization."""
    (model_directory / "classifier.joblib").write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="checksum differs"):
        load_model(model_directory)


def test_held_out_vocabulary_does_not_enter_training():
    """Pipeline fitting cannot learn a word that appears only in a later prediction."""
    from app.model import build_pipeline

    pipeline = build_pipeline().fit(["food cafe", "grocery store"], ["Food & Drink", "Groceries"])
    pipeline.predict(["heldoutuniquemarker"])
    vocabulary = pipeline.named_steps["features"].transformer_list[0][1].vocabulary_
    assert "heldoutuniquemarker" not in vocabulary
