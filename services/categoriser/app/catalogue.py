"""Conservative offline merchant recognition, separate from ML preprocessing."""

import csv
import re
import unicodedata
from pathlib import Path

from app.settings import CATEGORIES

AMBIGUOUS_NAMES = {"grab", "apple"}


def normalise_merchant(text: str) -> str:
    """Normalise case/space and explicit payment markers, preserving punctuation."""
    text = unicodedata.normalize("NFKC", text).casefold().strip()
    text = re.sub(r"^(?:(?:nets|card)\s*[*:/-]\s*)+", "", text)
    return " ".join(text.split())


class MerchantCatalogue:
    """Load a checked alias table and reject collisions rather than guess."""

    def __init__(self, rows: list[dict]):
        """Validate all names, families and categories before serving requests."""
        self.rows = rows
        self.entries = {}
        for row in rows:
            key = normalise_merchant(row["merchant_text"])
            if not key or key in AMBIGUOUS_NAMES or row["category"] not in CATEGORIES:
                raise ValueError(f"Invalid catalogue entry: {row}")
            if key in self.entries:
                raise ValueError(f"Normalised catalogue collision: {key}")
            if not row["merchant_group"].strip():
                raise ValueError("Catalogue family is empty")
            self.entries[key] = row

    @classmethod
    def from_csv(cls, path: Path):
        """Read only the simple, explicitly curated catalogue CSV."""
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != ["merchant_text", "merchant_group", "category"]:
                raise ValueError("Invalid catalogue schema")
            return cls(list(reader))

    def match(self, text: str) -> dict | None:
        """Match only an exact normalised verified name or explicit alias."""
        return self.entries.get(normalise_merchant(text))
