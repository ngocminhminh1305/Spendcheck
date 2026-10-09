"""Standalone GLiNER span extraction, without regex or typo correction."""

from functools import lru_cache


MODEL_NAME = "urchade/gliner_small-v2.1"
LABELS = ("amount", "merchant", "date")
DEFAULT_THRESHOLD = 0.5


@lru_cache(maxsize=1)
def load_model():
    """Load once per process. The first run downloads pretrained weights."""
    try:
        from gliner import GLiNER
    except ModuleNotFoundError as exc:
        if exc.name != "gliner":
            raise
        raise RuntimeError(
            "Install dependencies: python3 -m pip install -r requirements.txt"
        ) from exc

    model = GLiNER.from_pretrained(MODEL_NAME)
    model.to("cpu")
    model.eval()
    return model


def extract_gliner_entities(
    text: str, threshold: float = DEFAULT_THRESHOLD
) -> list[dict]:
    """Return original spans and uncalibrated scores, before normalization."""
    if not 0 < threshold < 1:
        raise ValueError("threshold must be between 0 and 1 (exclusive)")
    if not text.strip():
        return []

    predictions = load_model().predict_entities(text, list(LABELS), threshold=threshold)
    entities = []
    for prediction in predictions:
        start, end = prediction["start"], prediction["end"]
        label = prediction["label"]
        if label not in LABELS or not 0 <= start < end <= len(text):
            raise ValueError("GLiNER returned an invalid entity label or span")
        entities.append({
            "text": text[start:end],
            "label": label,
            "candidate_field": label,
            "start": start,
            "end": end,
            "score": float(prediction["score"]),
            "source": "gliner",
        })
    return entities
