"""Protect the user-selected real release and final-evaluation catalogue stages."""

import socket

from fastapi.testclient import TestClient

from app.main import create_app
from app.hybrid import load_bundle
from app.settings import ROOT
from scripts.evaluate_hybrid import verify_release
from scripts.release_hybrid import verify


def test_frozen_release_membership_and_configuration():
    """Preserve data exclusions, source hashes and the selected artifact configuration."""
    verify()
    bundle = ROOT / "bundles/default/manifest.json"
    for name in ["unseen", "operational"]:
        assert verify_release(bundle, name)["configuration"]["training_rows"] == 280
    recognition = ROOT / "bundles/default/recognition_manifest.json"
    assert verify_release(recognition, "recognition")["catalogue_version"] == "hybrid-v1-development"


def test_default_api_selected_artifact_offline(monkeypatch):
    """Exercise the actual final MiniLM without making predictions on final benchmark rows."""
    def deny_network(*args, **kwargs):
        """Reject any unexpected outbound connection during loading or inference."""
        raise AssertionError("Release attempted network access")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    model, catalogue, manifest = load_bundle(ROOT / "bundles/default/manifest.json")
    assert model.head.C == 1 and model.head.class_weight == "balanced"
    with TestClient(create_app()) as client:
        for text, expected in [("Watsons", "Health"), ("Octobox", "Groceries"),
                               ("NETS*NTUC FairPrice", "Groceries")]:
            result = client.post("/classify", json={"merchant": text}).json()
            assert result == {"category": expected, "confidence": None, "source": "lookup",
                              "model_version": "merchant-categoriser-v1"}
        result = client.post("/classify", json={"merchant": "zzzzzzzzzzz"}).json()
        probabilities = model.predict_proba(["zzzzzzzzzzz"])[0]
        assert result["model_version"] == "merchant-categoriser-v1"
        assert result["source"] == "model" and result["confidence"] < .5
        assert result["category"] == model.classes_[probabilities.argmax()]
        assert abs(result["confidence"] - float(probabilities.max())) < 1e-8
        for text in ["Grab", "Apple", "!!!"]:
            assert client.post("/classify", json={"merchant": text}).status_code == 422
