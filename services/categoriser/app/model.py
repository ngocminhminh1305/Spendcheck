"""Build, load and validate the portable scikit-learn model artifact."""

import hashlib
import json
import warnings
from pathlib import Path

import joblib
import sklearn
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer

from app.cleaning import clean_merchant
from app.settings import CATEGORIES, SEED


def clean_merchants(merchants: list[str]) -> list[str]:
    """Clean input strings inside the serialized training/inference pipeline."""
    return [clean_merchant(merchant) for merchant in merchants]


def build_pipeline() -> Pipeline:
    """Combine word and character TF-IDF with multiclass logistic regression."""
    return Pipeline([
        ("clean", FunctionTransformer(clean_merchants, validate=False)),
        ("features", FeatureUnion([
            ("words", TfidfVectorizer(ngram_range=(1, 2), lowercase=False,
                                     token_pattern=r"(?u)\b\w+\b")),
            ("characters", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                          lowercase=False)),
        ])),
        ("classifier", LogisticRegression(C=1, max_iter=2000, random_state=SEED)),
    ])


def file_hash(path: Path) -> str:
    """Return the SHA-256 of a file for artifact and dataset verification."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_model(directory: Path, metadata_path: Path | None = None) -> tuple[object, dict]:
    """Load trusted local artifacts, rejecting missing or incompatible models."""
    try:
        metadata = json.loads((metadata_path or directory / "metadata.json").read_text())
        artifact = directory / "classifier.joblib"
        if metadata["sklearn_version"] != sklearn.__version__:
            raise ValueError("scikit-learn version differs; install pinned requirements or retrain")
        if file_hash(artifact) != metadata["model_sha256"]:
            raise ValueError("model checksum differs from metadata")
        with warnings.catch_warnings():
            warnings.simplefilter("error", InconsistentVersionWarning)
            pipeline = joblib.load(artifact)
        if metadata.get("model_type") == "sentence_embedding":
            from app.embeddings import EmbeddingClassifier
            import importlib.metadata
            for package, version in metadata["encoder_packages"].items():
                if importlib.metadata.version(package).split("+")[0] != version.split("+")[0]:
                    raise ValueError(f"{package} version differs from candidate metadata")
            if file_hash(Path(__file__).with_name("cleaning.py")) != metadata["preprocessing_sha256"]:
                raise ValueError("preprocessing checksum differs from candidate metadata")
            actual = {str(path.relative_to(directory / "encoder")): file_hash(path)
                      for path in (directory / "encoder").rglob("*") if path.is_file()}
            if actual != metadata["encoder_files"]:
                raise ValueError("encoder checksums differ from metadata")
            pipeline = EmbeddingClassifier(directory / "encoder", pipeline)
        if set(pipeline.classes_) != set(CATEGORIES):
            raise ValueError("model does not contain the nine configured categories")
        return pipeline, metadata
    except Exception as error:
        raise RuntimeError(f"Cannot load classifier from {directory}: {error}") from error
