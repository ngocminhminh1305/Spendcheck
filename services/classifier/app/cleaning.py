"""Conservative cleaning shared by training and inference."""

import re
import unicodedata


def clean_merchant(merchant: str) -> str:
    """Normalise case and separators, stripping only leading NETS/CARD markers."""
    text = unicodedata.normalize("NFKC", merchant).casefold().strip()
    text = re.sub(r"^(?:(?:nets|card)\s*[*:/-]\s*)+", "", text)
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())

