"""Pretrained spaCy candidates with original text spans."""

from functools import lru_cache


MODEL_NAME = "en_core_web_sm"
LABEL_TO_FIELD = {"MONEY": "amount", "ORG": "merchant", "DATE": "date"}


@lru_cache(maxsize=1)
def load_model():
    """Load once per process, only when this optional layer is requested."""
    try:
        import spacy
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Install dependencies: python3 -m pip install -r requirements.txt"
        ) from exc
    try:
        # Keep tok2vec because NER may depend on its learned token features.
        return spacy.load(
            MODEL_NAME, exclude=["tagger", "parser", "attribute_ruler", "lemmatizer"]
        )
    except OSError as exc:
        raise RuntimeError(
            "Download the model first: python3 -m spacy download en_core_web_sm"
        ) from exc


def extract_spacy_entities(text: str) -> list[dict]:
    """Keep all spans for inspection; unsupported labels map to no field."""
    doc = load_model()(text)
    return [
        {
            "text": entity.text,
            "label": entity.label_,
            "candidate_field": LABEL_TO_FIELD.get(entity.label_),
            "start": entity.start_char,
            "end": entity.end_char,
            "source": "spacy",
        }
        for entity in doc.ents
    ]
