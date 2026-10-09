"""End-to-end transaction extraction pipeline."""

import re
from datetime import datetime

from app.layered import run_layers
from app.schemas import ExtractResponse


_DATE_TYPOS = {"yesterdat": "yesterday", "yesterdy": "yesterday"}


def _correct_date_word(match: re.Match[str]) -> str:
    word = match.group(0)
    # Broad fuzzy correction can corrupt names such as "Augustus".
    return _DATE_TYPOS.get(word.casefold(), word)


def preprocess_text(text: str) -> str:
    """Clean whitespace and conservatively fix likely date-word typos."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\b[A-Za-z]{5,}\b", _correct_date_word, cleaned)


def extract_transaction(
    text: str, reference_datetime: datetime, *, use_models: bool = True,
) -> ExtractResponse:
    """Preprocess, extract, normalize, validate, and structure one transaction."""
    result, _ = extract_transaction_with_trace(text, reference_datetime, use_models=use_models)
    return result


def extract_transaction_with_trace(text: str, reference_datetime: datetime, *, use_models: bool = True):
    cleaned = preprocess_text(text)
    result, trace = run_layers(cleaned, reference_datetime, use_models=use_models)
    # Model offsets refer to cleaned_text, whose length may differ from input.
    return result, {"input_text": text, "cleaned_text": cleaned, **trace}
