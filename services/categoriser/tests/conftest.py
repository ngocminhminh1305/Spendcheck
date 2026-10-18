"""Independent fixtures; no teammate services or live models are required."""

import joblib
import pytest
import sklearn

from app.model import build_pipeline, file_hash
from app.settings import CATEGORIES
from scripts.common import write_json


@pytest.fixture(scope="session")
def sample_pipeline():
    """Fit an isolated small model with clear, distinctive names for each category."""
    names = ["cafe tea meal", "supermarket grocery", "taxi bus ride", "retail clothes store",
             "cinema concert games", "electricity broadband bill", "medical clinic medicine",
             "university tuition course", "laundry postage haircut"]
    merchants = [name for name in names for _ in range(12)]
    labels = [category for category in CATEGORIES for _ in range(12)]
    return build_pipeline().fit(merchants, labels)


@pytest.fixture
def model_directory(tmp_path, sample_pipeline):
    """Save a complete test artifact without modifying the shipped model."""
    artifact = tmp_path / "classifier.joblib"
    joblib.dump(sample_pipeline, artifact)
    write_json(tmp_path / "metadata.json", {
        "model_version": "test", "data_status": "test fixture",
        "sklearn_version": sklearn.__version__, "model_sha256": file_hash(artifact),
    })
    return tmp_path
