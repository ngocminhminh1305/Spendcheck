"""Check the selected release; never train, select or overwrite assets."""
import json
from app.hybrid import load_bundle
from app.model import file_hash
from app.settings import ROOT
from scripts.prepare_hybrid import check as check_data, prepared_file
from scripts.release_sources import verify_sources

def verify() -> None:
    """Check source, metadata, model and frozen evaluation provenance together."""
    check_data()
    parity = json.loads((ROOT / "reports/verification/parity.json").read_text())
    if file_hash(ROOT / "bundles/evaluation/submitted_manifest.json") != parity["final_manifest_sha256"]:
        raise ValueError("Recorded parity manifest changed")
    recognition = json.loads((ROOT / "reports/evaluation/B_recognition/metrics.json").read_text())
    if file_hash(ROOT / "bundles/evaluation/recognition_manifest.json") != recognition["bundle_sha256"]:
        raise ValueError("Recorded recognition manifest changed")
    resources = json.loads((ROOT / "reports/verification/resources.json").read_text())
    if file_hash(ROOT / "bundles/evaluation/submitted_manifest.json") != resources["bundle_sha256"]:
        raise ValueError("Recorded resource manifest changed")
    for name in ['manifest.json','recognition_manifest.json']:
        path = ROOT / 'bundles/default' / name
        bundle = json.loads(path.read_text())
        verify_sources(bundle)
        if file_hash(ROOT / "reports/verification/evaluated_readiness.json") != bundle["functional_evidence_sha256"]:
            raise ValueError("Recorded readiness evidence changed")
        for filename, digest in bundle['audit']['evaluation_file_hashes'].items():
            if file_hash(prepared_file(filename)) != digest:
                raise ValueError(f'Frozen evaluation changed: {filename}')
        model, catalogue, _ = load_bundle(path)
        if model.head.C != 1 or model.head.class_weight != 'balanced':
            raise ValueError('Selected configuration changed')
    print('Selected release, evaluated parent and 372 checked labels verified')

def main() -> None:
    """Expose only the non-mutating integrity check."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check'])
    parser.parse_args()
    verify()

if __name__ == '__main__':
    main()
