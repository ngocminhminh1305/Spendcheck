"""Check the real HTTP service and optionally compare it against the local model."""

import argparse
import json
import urllib.error
import urllib.request

from pathlib import Path
from app.hybrid import categorise_merchant, load_bundle
from app.settings import ROOT, CATEGORIES


def request_json(url: str, body: dict | None = None) -> tuple[int, dict]:
    """Send JSON with a timeout and retain validation responses for smoke checks."""
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def smoke_api(base_url: str, compare_local: bool = True, bundle: Path = ROOT / "bundles/default/manifest.json") -> None:
    """Verify hybrid readiness, narrow ambiguity and optional local prediction parity."""
    checks = 0
    status, health = request_json(f"{base_url}/health")
    assert status == 200 and health["status"] == "ready", health
    checks += 1
    if compare_local:
        pipeline, catalogue, metadata = load_bundle(bundle)
        assert health["model_version"] == metadata["model_version"]
    for merchant in ("NETS*KOPITIAM", "NTUC FairPrice", "Chagee", "SGH", "K-Market",
                     "ABC Dental Clinic", "Happy Noodle House", "zzzzzzzzzzz"):
        status, result = request_json(f"{base_url}/classify", {"merchant": merchant})
        assert status == 200, result
        assert result["category"] in CATEGORIES and result["source"] in {"lookup", "model"}, result
        assert (result["confidence"] is None) == (result["source"] == "lookup"), result
        if compare_local:
            expected = categorise_merchant(merchant, pipeline, catalogue, metadata["model_version"])
            assert result["category"] == expected["category"] and result["source"] == expected["source"]
            if expected["confidence"] is not None:
                # macOS/Linux BLAS kernels can differ slightly despite identical assets.
                assert abs(result["confidence"] - expected["confidence"]) < 1e-6
        checks += 1
    for body in ({}, {"merchant": None}, {"merchant": " "}, {"merchant": "x" * 501},
                 {"merchant": "Grab"}, {"merchant": "Apple"}, {"merchant": "!!!"}):
        status, _ = request_json(f"{base_url}/classify", body)
        assert status == 422, (status, body)
        checks += 1
    print(f"{checks} HTTP checks passed at {base_url}; local parity={compare_local}")


def main() -> None:
    """Run against local Uvicorn or the Docker-mapped port."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    parser.add_argument("--bundle", type=Path, default=ROOT / "bundles/default/manifest.json")
    parser.add_argument("--no-local-comparison", action="store_true")
    args = parser.parse_args()
    smoke_api(args.base_url.rstrip("/"), not args.no_local_comparison, args.bundle)


if __name__ == "__main__":
    main()
