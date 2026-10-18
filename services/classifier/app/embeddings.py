"""Frozen, CPU-only sentence embeddings with an independently saved classifier head."""

from pathlib import Path
import numpy as np
from app.cleaning import clean_merchant


class EmbeddingClassifier:
    """Expose sklearn-like prediction methods without changing encoder weights."""

    def __init__(self, encoder_directory: Path, head):
        """Load only bundled encoder assets; never resolve a remote model at startup."""
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(1)
        self.encoder = SentenceTransformer(str(encoder_directory), device="cpu", local_files_only=True,
                                           trust_remote_code=False)
        self.encoder.eval()
        for parameter in self.encoder.parameters():
            parameter.requires_grad_(False)
        self.head = head
        self.classes_ = head.classes_

    def encode(self, merchants: list[str]) -> np.ndarray:
        """Apply the existing cleanup and produce unit-normalised frozen embeddings."""
        return self.encoder.encode([clean_merchant(text) for text in merchants], batch_size=32,
                                   normalize_embeddings=True, convert_to_numpy=True,
                                   show_progress_bar=False)

    def predict_proba(self, merchants: list[str]) -> np.ndarray:
        """Return head probabilities in the stored classifier's category order."""
        return self.head.predict_proba(self.encode(merchants))

    def predict(self, merchants: list[str]) -> np.ndarray:
        """Return raw categories without confidence-based abstention."""
        return self.classes_[self.predict_proba(merchants).argmax(axis=1)]
