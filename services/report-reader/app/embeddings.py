"""Text embeddings with a small local model (BAAI/bge-small-en-v1.5 via fastembed, ONNX on CPU).

Local embeddings keep ingestion free and reproducible; only answer generation calls the LLM.
The ingest job and the API must use the same model, or query and chunk vectors will not match.
"""

from collections.abc import Iterable

import numpy as np
from fastembed import TextEmbedding


class Embedder:
    def __init__(self, model_name: str, cache_dir: str | None = None):
        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_query(self, text: str) -> np.ndarray:
        # bge models expect a query instruction prefix; query_embed adds it.
        return next(iter(self._model.query_embed(text)))

    def embed_passages(self, texts: Iterable[str], batch_size: int = 64) -> list[np.ndarray]:
        return list(self._model.passage_embed(list(texts), batch_size=batch_size))
