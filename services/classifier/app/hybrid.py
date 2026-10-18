"""Verified lookup followed by the existing multiclass model; no rejection threshold."""

import json
from pathlib import Path

from app.catalogue import AMBIGUOUS_NAMES, MerchantCatalogue, normalise_merchant
from app.model import file_hash, load_model


class AmbiguousMerchant(ValueError):
    """Identify only the explicitly documented multi-service bare names."""


def load_bundle(path: Path):
    """Verify a portable bundle manifest and load its catalogue and fallback once."""
    path = path.resolve()
    manifest = json.loads(path.read_text())
    catalogue_path = (path.parent / manifest["catalogue_file"]).resolve()
    model_path = (path.parent / manifest["model_directory"]).resolve()
    metadata_path = (path.parent / manifest["fallback_metadata_file"]).resolve() if "fallback_metadata_file" in manifest else model_path / "metadata.json"
    if file_hash(metadata_path) != manifest["fallback_metadata_sha256"]:
        raise RuntimeError("Fallback metadata differs from bundle manifest")
    if file_hash(catalogue_path) != manifest["catalogue_sha256"]:
        raise RuntimeError("Catalogue checksum differs from bundle manifest")
    catalogue = MerchantCatalogue.from_csv(catalogue_path)
    model, metadata = load_model(model_path, metadata_path)
    if metadata["model_sha256"] != manifest["fallback_sha256"]:
        raise RuntimeError("Fallback differs from bundle manifest")
    return model, catalogue, manifest


def categorise_merchant(text: str, model, catalogue: MerchantCatalogue, version: str) -> dict:
    """Return a verified merchant default or the highest-probability ML category."""
    if normalise_merchant(text) in AMBIGUOUS_NAMES:
        raise AmbiguousMerchant("ambiguous_merchant: specify the service, e.g. GrabFood or Grab ride; only Apple is ambiguous")
    match = catalogue.match(text)
    if match:
        return {"category": match["category"], "confidence": None,
                "source": "lookup", "model_version": version}
    probabilities = model.predict_proba([text])[0]
    best = int(probabilities.argmax())
    return {"category": str(model.classes_[best]), "confidence": float(probabilities[best]),
            "source": "model", "model_version": version}
