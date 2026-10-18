"""Prepare a frozen development benchmark and manually train existing classifiers.

This utility never scores test rows, promotes models, downloads encoders, or changes
the API. Only current group-separated classification experiments are supported.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unicodedata

import joblib
import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedGroupKFold
from threadpoolctl import threadpool_limits

from app.cleaning import clean_merchant
from app.model import build_pipeline, file_hash
from app.settings import CATEGORIES, DATA, ROOT, SEED
from scripts.common import read_csv, write_csv, write_json
from scripts.encoder_utils import ENCODERS, cached_embeddings, object_hash
from scripts.metrics import score_predictions

DEFAULT_DATASET = DATA / "prepared/merchant_dataset.csv"
DEFAULT_SPLIT = DATA / "prepared/split.csv"
DEFAULT_RUN = ROOT / "runs" / "reproduction"
PARTITIONS = ("train", "validation", "test")
# Conservative split-only bundles: original merchant_group values are preserved.
# These prevent both direct name reuse and selected documented provider relations.
RELATED_GROUPS = (
    ("fairprice", "cheers", "unitypharmacy"),
    ("singtel", "gomo"),
    ("starhub", "giga", "myrepublic"),
    ("nus", "nuscoop"),
    ("googlecloud", "youtubepremium"),
    ("breadtalk", "toastbox", "dintaifung"),
    ("singaporegeneralhospital", "changigeneralhospital", "sengkanggeneralhospital",
     "kkwomensandchildrenshospital", "singaporenationaleyecentre", "singhealthpolyclinics"),
    ("nationaluniversityhospital", "ngtengfonggeneralhospital", "alexandrahospital",
     "nationaluniversitypolyclinics"),
    ("tantocksenghospital", "khooteckpuathospital", "nationalskincentre"),
)
SPLIT_FIELDS = ["row_id", "merchant_text", "merchant_group", "category", "split_group", "split"]


def local_path(path: Path) -> Path:
    """Restrict configurable inputs and outputs to this module, including symlinks."""
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError(f"Path must stay inside services/categoriser: {path}")
    return resolved


def dataset_rows(dataset: Path) -> list[dict]:
    """Read the three-column CSV and create stable internal IDs without editing it."""
    rows = read_csv(local_path(dataset))
    if not rows or list(rows[0]) != ["merchant_text", "merchant_group", "category"]:
        raise ValueError("Expected merchant_text,merchant_group,category exactly")
    seen = {}
    identities = {}
    related = {group: bundle[0] for bundle in RELATED_GROUPS for group in bundle}
    result = []
    for row in rows:
        if any(not value or value != value.strip() for value in row.values()):
            raise ValueError("Empty fields or surrounding whitespace in dataset")
        if row["category"] not in CATEGORIES or not clean_merchant(row["merchant_text"]):
            raise ValueError("Invalid category or unusable merchant text")
        cleaned = clean_merchant(row["merchant_text"])
        if cleaned in seen:
            raise ValueError(f"Duplicate cleaned merchant identity: {row['merchant_text']}")
        seen[cleaned] = row["merchant_group"]
        identity = "".join(c for c in unicodedata.normalize("NFKD", cleaned) if c.isalnum())
        if identity in identities and identities[identity] != row["merchant_group"]:
            raise ValueError(f"Cross-group spelling alias: {row['merchant_text']}")
        identities[identity] = row["merchant_group"]
        row_id = "new-" + object_hash(row)[:20]
        result.append({"row_id": row_id, **row,
                       "split_group": related.get(row["merchant_group"], row["merchant_group"])})
    if {r["category"] for r in result} != set(CATEGORIES):
        raise ValueError("Dataset must contain all nine categories")
    return sorted(result, key=lambda r: r["row_id"])


def make_split(rows: list[dict]) -> list[dict]:
    """Choose a fixed 70/15/15 group allocation using label balance only, never scores."""
    groups = sorted({r["split_group"] for r in rows})
    rng = np.random.default_rng(SEED)
    # Fixed bounded search balances row/category counts despite unequal family sizes.
    # It is split construction, not model or validation-performance selection.
    train_end = round(.70 * len(groups))
    validation_end = train_end + round(.15 * len(groups))
    counts = np.array([[sum(r["split_group"] == g and r["category"] == c for r in rows)
                        for c in CATEGORIES] for g in groups])
    target = np.array([.70, .15, .15])[:, None] * counts.sum(axis=0)
    best = None
    for _ in range(16384):
        permutation = rng.permutation(len(groups))
        chunks = np.split(permutation, [train_end, validation_end])
        actual = np.array([counts[chunk].sum(axis=0) for chunk in chunks])
        if np.any(actual < 3):
            continue
        loss = float(np.sum((actual - target) ** 2 / target))
        if best is None or loss < best[0]:
            best = (loss, {groups[i]: part for part, chunk in zip(PARTITIONS, chunks) for i in chunk})
    if best is None:
        raise ValueError("Cannot provide three rows per category/partition with these group constraints")
    return [{**r, "split": best[1][r["split_group"]]} for r in rows]


def check_split(rows: list[dict], manifest: list[dict]) -> None:
    """Reject stale data, missing rows, invalid categories and cross-partition identities."""
    if len(manifest) != len(rows) or len({r["row_id"] for r in manifest}) != len(rows):
        raise ValueError("Split has missing or duplicate rows")
    saved = [{k: r[k] for k in rows[0]} for r in manifest]
    if sorted(saved, key=lambda r: r["row_id"]) != rows:
        raise ValueError("Dataset or split-only grouping differs from the frozen manifest")
    for field in ("merchant_group", "split_group"):
        for group in {r[field] for r in manifest}:
            if len({r["split"] for r in manifest if r[field] == group}) != 1:
                raise ValueError(f"Cross-partition identity leakage: {group}")
    if {r["split"] for r in manifest} != set(PARTITIONS):
        raise ValueError("Invalid partition names")
    for part in PARTITIONS:
        if {r["category"] for r in manifest if r["split"] == part} != set(CATEGORIES):
            raise ValueError(f"Partition lacks a category: {part}")


def fold_rows(training: list[dict]) -> tuple[list[tuple], list[dict]]:
    """Derive identical train-only three-fold group CV for both frozen encoders."""
    labels = np.array([r["category"] for r in training])
    groups = np.array([r["split_group"] for r in training])
    folds = list(StratifiedGroupKFold(n_splits=3, shuffle=True, random_state=SEED)
                 .split(np.zeros(len(training)), labels, groups))
    saved = []
    for fold, (fit, held) in enumerate(folds):
        if set(groups[fit]) & set(groups[held]):
            raise ValueError("CV identity leakage")
        if set(labels[fit]) != set(CATEGORIES) or set(labels[held]) != set(CATEGORIES):
            raise ValueError("Training CV fold lacks a category")
        saved.extend({"row_id": training[i]["row_id"], "split_group": groups[i], "fold": str(fold)}
                     for i in held)
    return folds, sorted(saved, key=lambda r: r["row_id"])


def prepare(dataset: Path, split: Path, check_only: bool = False) -> list[dict]:
    """Create once or verify immutable split, provenance and shared CV-fold files."""
    dataset, split = local_path(dataset), local_path(split)
    if split == DATA / "prepared/split.csv":
        from scripts.prepare_hybrid import DIRECTORY, check
        if dataset != DIRECTORY / "merchant_dataset.csv":
            raise ValueError("Hybrid split requires its frozen expanded dataset")
        check()
        return read_csv(split)
    rows = dataset_rows(dataset)
    summary_path, folds_path = split.with_suffix(".json"), split.with_name(split.stem + "_folds.csv")
    existing = [p.exists() for p in (split, summary_path, folds_path)]
    if any(existing) and not all(existing):
        raise ValueError("Incomplete split bundle; preserve it and choose a new --split path")
    if check_only and not all(existing):
        raise ValueError("No frozen split; run prepare first")
    manifest = read_csv(split) if all(existing) else make_split(rows)
    check_split(rows, manifest)
    _, fold_manifest = fold_rows([r for r in manifest if r["split"] == "train"])
    summary = {"benchmark": "new development benchmark; overlaps earlier analysed merchant families",
               "seed": SEED, "target_fractions": [.70, .15, .15], "split_candidates": 16384,
               "minimum_category_rows_per_partition": 3,
               "dataset_sha256": file_hash(dataset), "related_group_bundles": RELATED_GROUPS,
               "assignments_sha256": object_hash(manifest),
               "rows_sha256": object_hash(rows), "folds_sha256": object_hash(fold_manifest),
               "partitions": {part: {
                   "rows": sum(r["split"] == part for r in manifest),
                   "merchant_families": len({r["merchant_group"] for r in manifest if r["split"] == part}),
                   "split_groups": len({r["split_group"] for r in manifest if r["split"] == part}),
                   "categories": dict(Counter(r["category"] for r in manifest if r["split"] == part))}
                   for part in PARTITIONS}}
    # Canonical JSON makes tuples and lists compare identically after serialization.
    summary = json.loads(json.dumps(summary))
    if all(existing):
        if read_csv(folds_path) != fold_manifest or json.loads(summary_path.read_text()) != summary:
            raise ValueError("Frozen split provenance or CV folds differ")
    else:
        write_csv(split, manifest, SPLIT_FIELDS)
        write_csv(folds_path, fold_manifest, ["row_id", "split_group", "fold"])
        write_json(summary_path, summary)
    print(json.dumps(summary["partitions"], indent=2))
    return manifest


def write_metrics(model, rows: list[dict], probabilities, directory: Path, part: str) -> dict:
    """Write raw full-coverage scores, confusion matrix and row-level probabilities."""
    predicted = model.classes_[probabilities.argmax(axis=1)].tolist()
    metrics = score_predictions([r["category"] for r in rows], predicted)
    write_json(directory / f"{part}.json", metrics)
    write_csv(directory / f"{part}_confusion_matrix.csv",
              [{"true_category": cat, **dict(zip(CATEGORIES, metrics["confusion_matrix"][i]))}
               for i, cat in enumerate(CATEGORIES)], ["true_category", *CATEGORIES])
    write_csv(directory / f"{part}_per_category.csv",
              [{"category": cat, **metrics["per_category"][cat]} for cat in CATEGORIES],
              ["category", "precision", "recall", "f1-score", "support"])
    predictions = [{"row_id": row["row_id"], "merchant_text": row["merchant_text"],
                    "merchant_group": row["merchant_group"], "true_category": row["category"],
                    "predicted_category": predicted[i], "confidence": float(probabilities[i].max())}
                   for i, row in enumerate(rows)]
    write_csv(directory / f"{part}_predictions.csv", predictions, list(predictions[0]))
    return {key: metrics[key] for key in ("rows", "accuracy", "macro_f1")}


def train(name: str, dataset: Path, split: Path, run: Path, compare_class_weight: bool = False, encoder_directory: Path | None = None) -> None:
    """Manually fit one existing classifier and score train/validation only."""
    dataset, split, run = local_path(dataset), local_path(split), local_path(run)
    manifest = prepare(dataset, split, check_only=True)
    training = [r for r in manifest if r["split"] == "train"]
    validation = [r for r in manifest if r["split"] == "validation"]
    destination, reports = run / "models" / name, run / "reports" / name
    if destination.exists() or reports.exists():
        raise ValueError("Model/report output exists; preserve it and choose a new --run-dir")
    folds, fold_manifest = fold_rows(training)
    metadata = {"model_version": f"new-merchant-{name}", "mode": "new_merchant_development",
                "data_status": "source-checked constructed descriptions; development benchmark",
                "seed": SEED, "sklearn_version": sklearn.__version__,
                "dataset_file": str(dataset.relative_to(ROOT)), "dataset_sha256": file_hash(dataset),
                "split_file": str(split.relative_to(ROOT)), "split_sha256": file_hash(split),
                "training_rows": len(training), "validation_rows": len(validation),
                "categories": list(CATEGORIES), "folds_sha256": object_hash(fold_manifest),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "test_evaluation": "not performed", "promotion": "not performed"}
    # Only the user-invoked train command reaches model fitting or encoder loading.
    if name == "tfidf":
        scores = []
        if compare_class_weight:
            # Fit vocabulary separately in each fold; validation text never builds TF-IDF features.
            for weight in [None, "balanced"]:
                values = []
                with threadpool_limits(limits=1):
                    for fit, held in folds:
                        fitted = build_pipeline().set_params(classifier__class_weight=weight)
                        fitted.fit([training[i]["merchant_text"] for i in fit],
                                   [training[i]["category"] for i in fit])
                        values.append(float(f1_score([training[i]["category"] for i in held],
                            fitted.predict([training[i]["merchant_text"] for i in held]),
                            labels=list(CATEGORIES), average="macro", zero_division=0)))
                scores.append({"C": 1, "class_weight": weight, "fold_macro_f1": values,
                               "mean_macro_f1": float(np.mean(values))})
        chosen_weight = max(scores, key=lambda r: (r["mean_macro_f1"], r["class_weight"] is None))["class_weight"] if scores else None
        model = build_pipeline()
        if compare_class_weight:
            model.set_params(classifier__class_weight=chosen_weight)
        with threadpool_limits(limits=1):
            model.fit([r["merchant_text"] for r in training], [r["category"] for r in training])
        head = model
        train_prob = model.predict_proba([r["merchant_text"] for r in training])
        validation_prob = model.predict_proba([r["merchant_text"] for r in validation])
        metadata.update(selected_C=1, selected_class_weight=chosen_weight, cv_results=scores, model_type="tfidf")
    else:
        from app.embeddings import EmbeddingClassifier

        source_dir = local_path(encoder_directory) if encoder_directory else ROOT / "models" / name
        source = json.loads((source_dir / "source.json").read_text())
        original = json.loads((source_dir / "metadata.json").read_text())
        if source["encoder_id"] != ENCODERS[name] or any(source[k] != original[k] for k in source):
            raise ValueError("Unexpected bundled encoder identity")
        assets = {str(p.relative_to(source_dir / "encoder")): file_hash(p)
                  for p in (source_dir / "encoder").rglob("*") if p.is_file()}
        if not assets or assets != original["encoder_files"]:
            raise ValueError("Bundled encoder checksums differ")
        packages = {p: importlib.metadata.version(p) for p in ["sentence-transformers", "transformers", "torch"]}
        model = EmbeddingClassifier(source_dir / "encoder", SimpleNamespace(classes_=np.array(CATEGORIES)))
        key = {**source, "encoder_files_sha256": object_hash(assets), "packages": packages,
               "cleaning_sha256": file_hash(ROOT / "app/cleaning.py"),
               "embedding_code_sha256": file_hash(ROOT / "app/embeddings.py"),
               "rows_sha256": object_hash(training + validation), "normalised": True}
        embeddings, reused = cached_embeddings(model, training + validation, key, run / "cache" / f"{name}.npy")
        x, x_validation = embeddings[:len(training)], embeddings[len(training):]
        labels = np.array([r["category"] for r in training])
        scores = []
        with threadpool_limits(limits=1):
            for weight in ([None, "balanced"] if compare_class_weight else [None]):
                for c in [.1, 1, 10]:
                    values = []
                    for fit, held in folds:
                        fitted = LogisticRegression(C=c, class_weight=weight, max_iter=2000, random_state=SEED).fit(x[fit], labels[fit])
                        values.append(float(f1_score(labels[held], fitted.predict(x[held]),
                                                     labels=list(CATEGORIES), average="macro", zero_division=0)))
                    scores.append({"C": c, "class_weight": weight, "fold_macro_f1": values, "mean_macro_f1": float(np.mean(values))})
            winner = max(scores, key=lambda r: (r["mean_macro_f1"], r["class_weight"] is None, -r["C"]))
            chosen = winner["C"]
            head = LogisticRegression(C=chosen, class_weight=winner["class_weight"], max_iter=2000, random_state=SEED).fit(x, labels)
        model.head, model.classes_ = head, head.classes_
        train_prob, validation_prob = head.predict_proba(x), head.predict_proba(x_validation)
        metadata.update(**source, model_type="sentence_embedding", encoder_files=assets,
                        encoder_packages=packages, preprocessing_sha256=file_hash(ROOT / "app/cleaning.py"),
                        selected_C=chosen, selected_class_weight=winner["class_weight"], cv_results=scores, frozen_encoder=True,
                        normalised_embeddings=True, embedding_dimension=int(x.shape[1]),
                        embedding_provenance=key, embedding_cache_reused=reused)
    destination.mkdir(parents=True, exist_ok=False)
    if name != "tfidf":
        shutil.copytree(source_dir / "encoder", destination / "encoder")
        write_json(destination / "source.json", source)
    artifact = destination / "classifier.joblib"
    joblib.dump(head, artifact, compress=3)
    reloaded = joblib.load(artifact)
    probe = [r["merchant_text"] for r in validation] if name == "tfidf" else x_validation
    np.testing.assert_allclose(reloaded.predict_proba(probe), validation_prob, rtol=1e-6, atol=1e-7)
    metadata["model_sha256"] = file_hash(artifact)
    write_json(destination / "metadata.json", metadata)
    metrics = {part: write_metrics(model, rows, prob, reports, part) for part, rows, prob in
               [("train", training, train_prob), ("validation", validation, validation_prob)]}
    write_json(reports / "summary.json", {"model": name, "selected_C": metadata["selected_C"],
               "selected_class_weight": metadata["selected_class_weight"],
               "metrics": metrics, "test_evaluation": "not performed",
               "confidence": "raw maximum probability; no threshold filtering; uncalibrated"})
    print(json.dumps(metrics, indent=2))
    print(f"Saved independent candidate: {destination}\nReports: {reports}")


def main() -> None:
    """Prepare/check shared data or train one candidate, with configurable local paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "check", "train"])
    parser.add_argument("model", nargs="?", choices=["tfidf", "minilm", "mpnet"])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--encoder-dir", type=Path, help="Bundled encoder source/metadata/encoder directory; required if omitted from checkout")
    parser.add_argument("--compare-class-weight", action="store_true", help="Select unweighted/balanced by training-only CV")
    args = parser.parse_args()
    try:
        if args.command == "train":
            if args.model is None:
                parser.error("train requires tfidf, minilm or mpnet")
            train(args.model, args.dataset, args.split, args.run_dir, args.compare_class_weight, args.encoder_dir)
        else:
            if args.model is not None:
                parser.error("model is only used with train")
            prepare(args.dataset, args.split, check_only=args.command == "check")
    except (ValueError, FileNotFoundError) as error:
        parser.exit(2, f"Stopped: {error}\n")


if __name__ == "__main__":
    main()
