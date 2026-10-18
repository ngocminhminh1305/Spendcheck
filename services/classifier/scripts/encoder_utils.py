"""Frozen encoder provenance, explicit asset preparation and embedding cache."""
import hashlib
import json
from pathlib import Path
import numpy as np
from app.model import file_hash
from scripts.common import write_json
from app.settings import ROOT
CACHE = ROOT / ".encoder_cache"

ENCODERS = {"minilm": "sentence-transformers/all-MiniLM-L6-v2",
            "mpnet": "sentence-transformers/all-mpnet-base-v2"}

def object_hash(value) -> str:
    """Hash a canonical JSON object to detect changed cache conditions."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

def download_encoder(name: str, destination: Path, revision: str) -> dict:
    """Resolve an immutable upstream revision and bundle only native CPU inference assets."""
    from huggingface_hub import snapshot_download
    from sentence_transformers import SentenceTransformer

    source = snapshot_download(ENCODERS[name], revision=revision, cache_dir=str(CACHE / "hub"),
                               allow_patterns=["*.json", "*.txt", "*.safetensors", "*.model", "README.md", "LICENSE*"])
    encoder = SentenceTransformer(source, device="cpu", local_files_only=True, trust_remote_code=False)
    encoder.save_pretrained(str(destination), create_model_card=False)
    # Preserve the upstream model card/license alongside the independently bundled assets.
    import shutil
    for filename in ["README.md", "LICENSE", "LICENSE.txt"]:
        if (Path(source) / filename).exists():
            shutil.copy2(Path(source) / filename, destination / filename)
    return {"encoder_id": ENCODERS[name], "encoder_revision": revision}

def cached_embeddings(encoder, rows: list[dict], key: dict, path: Path) -> tuple[np.ndarray, bool]:
    """Encode once per exact provenance key and verify cached array bytes on reuse."""
    manifest_path = path.with_suffix(".json")
    if path.exists() and manifest_path.exists():
        saved = json.loads(manifest_path.read_text())
        if saved["key"] == key and saved["sha256"] == file_hash(path):
            array = np.load(path, allow_pickle=False)
            if array.shape[0] == len(rows) and np.isfinite(array).all():
                return array, True
        raise ValueError("Embedding cache provenance or checksum differs; preserve and use a new cache")
    array = encoder.encode([r["merchant_text"] for r in rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, array, allow_pickle=False)
    write_json(manifest_path, {"key": key, "sha256": file_hash(path), "shape": list(array.shape)})
    return array, False

def main() -> None:
    """Explicitly prepare a fixed encoder revision for optional manual reproduction."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=list(ENCODERS))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        parser.error("Use a new directory inside this module; never overwrite existing assets")
    revision = json.loads((ROOT / "bundles/training_encoders.json").read_text())[args.model]["encoder_revision"]
    source = download_encoder(args.model, output / "encoder", revision)
    assets = {str(p.relative_to(output / "encoder")): file_hash(p)
              for p in (output / "encoder").rglob("*") if p.is_file()}
    write_json(output / "source.json", source)
    write_json(output / "metadata.json", {**source, "encoder_files": assets})

if __name__ == "__main__":
    main()
