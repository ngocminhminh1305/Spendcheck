"""Check the new benchmark without training real classifiers or loading encoders."""

import json
import shutil

import numpy as np
import pytest

from app.settings import CATEGORIES, ROOT
from scripts import new_dataset as workflow
from scripts.common import read_csv, write_csv, write_json


class FakeClassifier:
    """Exercise orchestration and serialization without fitting a real classifier."""

    fits = []

    def __init__(self, **kwargs):
        """Expose a stable class order and record requested hyperparameters."""
        self.classes_ = np.array(CATEGORIES)
        self.options = kwargs

    def fit(self, x, labels):
        """Record fitting inputs instead of learning weights."""
        self.fits.append((list(x), list(labels), self.options))
        return self

    def set_params(self, **kwargs):
        """Record pipeline weight settings without fitting real TF-IDF features."""
        self.options.update(kwargs)
        return self

    def predict_proba(self, x):
        """Return finite normalised probabilities for report/serialization checks."""
        return np.tile([.6] + [.05] * 8, (len(x), 1))

    def predict(self, x):
        """Return categories consistent with the synthetic probabilities."""
        return np.repeat(self.classes_[0], len(x))


class FakeEncoder:
    """Replace expensive sentence encoders with a deterministic feature stub."""

    encoded = []

    def __init__(self, directory, head):
        """Expose the same lightweight interface as EmbeddingClassifier."""
        self.classes_ = head.classes_

    def encode(self, merchants):
        """Record exactly which texts entered feature extraction."""
        self.encoded.extend(merchants)
        return np.ones((len(merchants), 2))


@pytest.fixture
def isolated_workflow(tmp_path, monkeypatch):
    """Copy only new input data into an isolated, module-shaped test directory."""
    monkeypatch.setattr(workflow, "ROOT", tmp_path)
    path = tmp_path / "data.csv"
    shutil.copy2(ROOT / "data/sources/new_merchant_dataset.csv", path)
    return path, tmp_path / "split.csv", tmp_path / "run"


def test_frozen_split_and_shared_folds():
    """The shipped split is deterministic, isolated and identical for all candidates."""
    rows = workflow.dataset_rows(workflow.DEFAULT_DATASET)
    manifest = workflow.prepare(workflow.DEFAULT_DATASET, workflow.DEFAULT_SPLIT, check_only=True)
    assert workflow.prepare(workflow.DEFAULT_DATASET, workflow.DEFAULT_SPLIT, check_only=True) == manifest
    assert len(rows) == 372
    assert [sum(r["split"] == p for r in manifest) for p in workflow.PARTITIONS] == [280, 45, 47]
    for p in workflow.PARTITIONS:
        selected = [r for r in manifest if r["split"] == p]
        assert min(sum(r["category"] == c for r in selected) for c in CATEGORIES) >= 3
    training = [r for r in manifest if r["split"] == "train"]
    folds, saved = workflow.fold_rows(training)
    assert saved == read_csv(workflow.DEFAULT_SPLIT.with_name("folds.csv"))
    for fit, held in folds:
        assert {training[i]["split_group"] for i in fit}.isdisjoint(
            {training[i]["split_group"] for i in held})
    # Strict superset of merchant_group protection: consumer brands stay together too.
    for bundle in workflow.RELATED_GROUPS:
        assert len({r["split"] for r in manifest if r["merchant_group"] in bundle}) == 1


def test_repeated_preparation_is_read_only(isolated_workflow):
    """Rechecking a frozen bundle must not rewrite it; changed inputs are rejected."""
    dataset, split, _ = isolated_workflow
    workflow.prepare(dataset, split)
    paths = [split, split.with_suffix(".json"), split.with_name("split_folds.csv")]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    workflow.prepare(dataset, split, check_only=True)
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths} == before
    rows = read_csv(dataset)
    rows[0]["merchant_text"] += " changed"
    write_csv(dataset, rows, list(rows[0]))
    with pytest.raises(ValueError, match="differs"):
        workflow.prepare(dataset, split, check_only=True)


def test_cross_group_cleaned_alias_rejected(isolated_workflow):
    """Different family IDs cannot hide the same normalised merchant text."""
    dataset, _, _ = isolated_workflow
    rows = read_csv(dataset)
    rows.append({**rows[0], "merchant_group": "unrelated", "merchant_text": rows[0]["merchant_text"].upper()})
    write_csv(dataset, rows, list(rows[0]))
    with pytest.raises(ValueError, match="Duplicate cleaned"):
        workflow.dataset_rows(dataset)


def test_no_paths_outside_module(tmp_path):
    """Configurable paths cannot target a teammate's module or external location."""
    with pytest.raises(ValueError, match="inside services/classifier"):
        workflow.local_path(tmp_path / "outside.csv")


def test_cross_group_punctuation_alias_rejected(isolated_workflow):
    """Space/punctuation variants cannot masquerade as unrelated families."""
    dataset, _, _ = isolated_workflow
    rows = read_csv(dataset)
    rows.append({"merchant_text": "MrCoconut", "merchant_group": "another_brand", "category": "Food & Drink"})
    write_csv(dataset, rows, list(rows[0]))
    with pytest.raises(ValueError, match="Cross-group spelling alias"):
        workflow.dataset_rows(dataset)


def test_partition_tampering_rejected(isolated_workflow):
    """Swapping validation/test identities cannot silently change the benchmark."""
    dataset, split, _ = isolated_workflow
    manifest = workflow.prepare(dataset, split)
    validation = next(r for r in manifest if r["split"] == "validation")
    validation["split"] = "test"
    write_csv(split, manifest, workflow.SPLIT_FIELDS)
    with pytest.raises(ValueError):
        workflow.prepare(dataset, split, check_only=True)


@pytest.mark.parametrize("name", ["tfidf", "minilm", "mpnet"])
@pytest.mark.parametrize("compare_weights", [False, True])
def test_training_orchestration_without_real_fitting(name, compare_weights, isolated_workflow, monkeypatch):
    """All entry points exclude test texts, preserve parameters and produce reports."""
    import app.embeddings

    dataset, split, run = isolated_workflow
    manifest = workflow.prepare(dataset, split)
    FakeClassifier.fits = []
    FakeEncoder.encoded = []
    monkeypatch.setattr(workflow, "build_pipeline", FakeClassifier)
    monkeypatch.setattr(workflow, "LogisticRegression", FakeClassifier)
    monkeypatch.setattr(app.embeddings, "EmbeddingClassifier", FakeEncoder)
    monkeypatch.setattr(workflow, "ROOT", run.parent)
    for filename in ["cleaning.py", "embeddings.py"]:
        target = run.parent / "app" / filename
        target.parent.mkdir(exist_ok=True)
        target.write_text("# Test-only provenance placeholder\n")
    if name != "tfidf":
        source = run.parent / "models" / name
        encoder = source / "encoder"
        encoder.mkdir(parents=True)
        (encoder / "test_weights").write_bytes(b"stub, never loaded by a real encoder")
        provenance = {"encoder_id": workflow.ENCODERS[name], "encoder_revision": "test-fixed-revision"}
        write_json(source / "source.json", provenance)
        write_json(source / "metadata.json", {**provenance,
                   "encoder_files": {"test_weights": workflow.file_hash(encoder / "test_weights")}})
    workflow.train(name, dataset, split, run, compare_class_weight=compare_weights)
    destination = run / "models" / name
    metadata = json.loads((destination / "metadata.json").read_text())
    assert metadata["selected_C"] == (1 if name == "tfidf" else .1)
    assert "threshold" not in metadata and metadata["test_evaluation"] == "not performed"
    for part in ["train", "validation"]:
        report = run / "reports" / name
        metrics = json.loads((report / f"{part}.json").read_text())
        assert len(metrics["confusion_matrix"]) == 9
        predictions = read_csv(report / f"{part}_predictions.csv")
        assert {r["row_id"] for r in predictions} == {r["row_id"] for r in manifest if r["split"] == part}
        assert {"merchant_text", "true_category", "predicted_category", "confidence"} <= set(predictions[0])
    training_texts = {r["merchant_text"] for r in manifest if r["split"] == "train"}
    test_texts = {r["merchant_text"] for r in manifest if r["split"] == "test"}
    if name == "tfidf":
        assert set(FakeClassifier.fits[-1][0]) == training_texts
        if compare_weights:
            assert len(FakeClassifier.fits) == 7
            assert {r['class_weight'] for r in metadata['cv_results']} == {None, 'balanced'}
            assert {r['C'] for r in metadata['cv_results']} == {1}
    else:
        assert test_texts.isdisjoint(FakeEncoder.encoded)
        assert len(FakeEncoder.encoded) == 249  # 204 train + 45 validation; encoded once.
        assert len(FakeClassifier.fits) == (19 if compare_weights else 10)
        assert all(len(labels) <= 204 for _, labels, _ in FakeClassifier.fits)
    assert not list(run.rglob("test_predictions.csv"))
    with pytest.raises(ValueError, match="output exists"):
        workflow.train(name, dataset, split, run)
