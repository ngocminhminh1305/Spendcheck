"""Frozen-embedding cache safety."""
import numpy as np
import pytest
from scripts.encoder_utils import cached_embeddings

def test_embedding_cache_reuse_and_invalidation(tmp_path):
    """Repeated folds use identical saved vectors; changed provenance cannot reuse them."""
    class Encoder:
        """Count extraction calls without requiring pretrained weights."""
        calls = 0

        def encode(self, merchants):
            """Return fixed, finite unit vectors for a tiny cache test."""
            self.calls += 1
            return np.ones((len(merchants), 1), dtype=np.float32)

    encoder = Encoder()
    rows = [{'merchant_text': 'cafe'}, {'merchant_text': 'taxi'}]
    path = tmp_path / 'cache.npy'
    first, reused = cached_embeddings(encoder, rows, {'revision': 'a'}, path)
    second, reused2 = cached_embeddings(encoder, rows, {'revision': 'a'}, path)
    assert not reused and reused2 and encoder.calls == 1
    np.testing.assert_array_equal(first, second)
    with pytest.raises(ValueError, match='provenance'):
        cached_embeddings(encoder, rows, {'revision': 'b'}, path)
    path.write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='checksum'):
        cached_embeddings(encoder, rows, {'revision': 'a'}, path)
