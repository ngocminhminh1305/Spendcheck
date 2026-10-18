"""Verify evaluated manifest provenance and exact final source inventories."""
import json
from app.model import file_hash
from app.settings import ROOT


def verify_sources(bundle: dict) -> None:
    """Bind final sources to evaluated evidence without relaxing source or asset hashes."""
    if file_hash(ROOT / 'bundles/evaluation/manifest.json') != bundle['evaluated_manifest_sha256']:
        raise ValueError('Evaluated parent manifest changed')
    metadata = ROOT / 'models/minilm/metadata.json'
    if file_hash(metadata) != bundle['evaluated_model_metadata_sha256']:
        raise ValueError('Original model metadata changed')
    expected = set(bundle['runtime_sha256'])
    actual = {str(p.relative_to(ROOT)) for p in (ROOT / 'app').glob('*.py')}
    if {p for p in expected if p.startswith('app/')} != actual:
        raise ValueError('Application inventory changed')
    for name, digest in bundle['runtime_sha256'].items():
        if file_hash(ROOT / name) != digest:
            raise ValueError(f'Final source changed: {name}')
