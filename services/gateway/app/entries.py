"""Typed entry -> draft transaction: Module 1 (extract) then Module 2 (categorise).

Nothing is saved here. The website shows the draft, the user fixes anything missing or doubtful,
and only then POSTs it to /api/transactions. That keeps a wrong guess out of the database.
"""

import re
from datetime import datetime

from .schemas import Draft
from .services import Services

LOW_CONFIDENCE = 0.5          # below this an ML category is shown as "suggested, please check"
_RIDE_HINT = re.compile(r"(?i)\b(?:to|from)\b")


def parse_entry(text: str, now: datetime, services: Services) -> Draft:
    extracted = services.extract(text, now)
    notes: list[str] = []

    entry_date = extracted.get("date")
    if entry_date is None:
        entry_date = now.date().isoformat()
        notes.append("No date mentioned, so today's date is used.")

    merchant = extracted.get("merchant")
    category = source = confidence = None
    if merchant:
        result = services.classify(merchant)
        # Module 2 rejects a bare "Grab" (ride or food delivery?) and suggests "Grab ride".
        # An entry with a destination ("grab to school 14.60") is a ride, so ask again that way.
        if "error" in result and _RIDE_HINT.search(text):
            retry = services.classify(f"{merchant} ride")
            if "error" not in retry:
                result = retry
                notes.append(f'"{merchant}" can mean a ride or food delivery; treated as a ride because a destination is given.')
        if "error" in result:
            notes.append(f'Could not pick a category for "{merchant}". Please choose one.')
        else:
            category, source, confidence = result["category"], result["source"], result["confidence"]
            if source == "model" and confidence is not None and confidence < LOW_CONFIDENCE:
                notes.append(f"{category} is a best guess for an unfamiliar merchant; please check it.")

    missing = [f for f in ("amount", "merchant") if extracted.get(f) is None]
    if category is None:
        missing.append("category")
    needs_review = bool(missing) or (source == "model" and (confidence or 0) < LOW_CONFIDENCE)
    return Draft(text=text, amount=extracted.get("amount"), merchant=merchant, date=entry_date,
                 category=category, category_source=source, category_confidence=confidence,
                 missing_fields=missing, needs_review=needs_review, notes=notes)
