"""Reject source tampering while preserving the evaluated parent release."""
import json
import shutil
import pytest
from app.settings import ROOT
import scripts.release_sources as integrity


@pytest.mark.parametrize('tamper', ['app/cleaning.py', 'app/unexpected.py',
                                  'bundles/evaluation/manifest.json',
                                  'models/minilm/metadata.json'])
def test_source_integrity_rejects_changes(tmp_path, monkeypatch, tamper):
    """Final sources cannot bypass manifest, inventory or model metadata checks."""
    bundle = json.loads((ROOT / 'bundles/default/manifest.json').read_text())
    paths = set(bundle['runtime_sha256']) | {'bundles/evaluation/manifest.json',
        'models/minilm/metadata.json'}
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(ROOT / relative, target)
    monkeypatch.setattr(integrity, 'ROOT', tmp_path)
    integrity.verify_sources(bundle)
    path = tmp_path / tamper
    path.write_text((path.read_text() if path.exists() else '') + '\n# unrecorded change\n')
    with pytest.raises(ValueError):
        integrity.verify_sources(bundle)
