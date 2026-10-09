"""Regex -> spaCy -> GLiNER, with explicit acceptance and rejection states."""

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from threading import Lock

from app.extractor import (
    _parse_money, extract_amount, extract_date, extract_merchant,
    find_amount_candidates, has_multiple_transactions,
    extract_subscription_provider,
)
from app.gliner_extractor import extract_gliner_entities
from app.schemas import ExtractResponse
from app.spacy_extractor import extract_spacy_entities


FIELDS = ("amount", "merchant", "date")
# These are acceptance policies, not calibrated probability estimates.
GLINER_ACCEPT_THRESHOLD = 0.7
_MODEL_LOCK = Lock()  # Avoid simultaneous model loading/inference on an 8 GB Mac.
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_WEEKDAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
DATE_PHRASE = re.compile(
    rf"(?ix)\b(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}|"
    rf"\d{{1,2}}\s+{_MONTH}\s+\d{{4}}|{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}|"
    rf"(?:last\s+)?{_WEEKDAY}|today|yesterday|tomorrow|"
    r"this\s+(?:morning|afternoon|evening|night)|"
    r"(?:a|an|one|two|three|four|five|six|seven|\d+)\s+(?:days?|weeks?|months?)\s+ago)\b"
)
_GENERIC_MERCHANTS = {
    "breakfast", "lunch", "dinner", "coffee", "food", "groceries", "shop",
    "store", "home", "work", "school", "bucks", "dollars", "sgd", "s",
    "premium", "subscription", "membership", "plan",
}
_SENTENCE_WORDS = re.compile(
    r"(?i)\b(?:i|me|my|spent|spend|paid|pay|buy|bought|charged|cost|costs|"
    r"for|or|and|met|friends|subscribe|subscribed|subscribing|yesterday|today|tomorrow)\b"
)


class ModelUnavailableError(RuntimeError):
    """An ML layer failed operationally; this is not a missing transaction field."""


@dataclass
class Decision:
    state: str = "missing"
    value: float | str | date | None = None
    source: str | None = None
    history: list[dict] = field(default_factory=list)

    def record(self, layer: str, state: str, reason: str, value=None) -> None:
        self.state = state
        self.value = value if state == "accepted" else None
        self.source = layer if state in ("accepted", "rejected") else None
        self.history.append({"layer": layer, "state": state, "reason": reason})


def valid_merchant(value: str) -> bool:
    """Filter obviously unsuitable spans; this does not prove a business exists."""
    return bool(
        value and len(value) <= 80 and re.search(r"[A-Za-z]", value)
        and value.casefold() not in _GENERIC_MERCHANTS
        and not _SENTENCE_WORDS.search(value)
        and not DATE_PHRASE.search(value)
        and not re.search(r"(?i)\$|\bSGD\b", value)
        and not re.match(r"(?i)^(?:at|from|to|on)\b", value)
    )


def strong_rule_merchant(text: str, merchant: str) -> bool:
    if not valid_merchant(merchant):
        return False
    if extract_subscription_provider(text) == merchant:
        return True
    name = re.escape(merchant)
    return bool(
        re.search(rf"(?i)\b(?:at|from|to|on)\s+{name}(?=$|[\s.,!?;])", text)
        or re.match(rf"(?i)^(?:(?:buy|bought|order|ordered)\s+)?{name}\s+(?:S\$|\$|SGD\s*)?\d", text)
        or re.match(rf"(?i)^(?:S\$|\$|SGD\s*)?\d[\d,.]*\s+{name}(?=$|\s)", text)
    )


def strong_rule_amount(text: str) -> bool:
    """A bare number requires more than a nearby word like 'yesterday'."""
    if re.search(r"(?i)\$|\b(?:SGD|bucks?|dollars?|spent|paid|cost|costs|charged)\b", text):
        return True
    merchant = extract_merchant(text)
    return bool(merchant and strong_rule_merchant(text, merchant))


def normalize_date(value: str, reference: datetime) -> date | None:
    # A model label alone must not make "Kopitiam 8" into a date.
    if not DATE_PHRASE.fullmatch(value.strip()):
        return None
    return extract_date(value, reference)


def rule_decisions(text: str, reference: datetime) -> dict[str, Decision]:
    decisions = {name: Decision() for name in FIELDS}
    if has_multiple_transactions(text):
        for decision in decisions.values():
            decision.record("validation", "rejected", "Multiple transactions are unsupported")
        return decisions

    amount = extract_amount(text)
    candidates = find_amount_candidates(text)
    if amount is not None and strong_rule_amount(text):
        decisions["amount"].record("regex", "accepted", "One valid amount candidate", amount)
    elif amount is not None:
        decisions["amount"].record("regex", "uncertain", "Bare number lacks clear spending context")
    elif candidates:
        decisions["amount"].record("validation", "rejected", "Invalid or competing amount candidates")

    merchant = extract_merchant(text)
    if merchant and strong_rule_merchant(text, merchant):
        decisions["merchant"].record("regex", "accepted", "Explicit merchant marker or compact entry", merchant)
    elif merchant:
        decisions["merchant"].record("regex", "uncertain", "Merchant rule lacks strong sentence evidence")

    mentions = list(DATE_PHRASE.finditer(text))
    dates = [normalize_date(match.group(), reference) for match in mentions]
    if dates:
        if None in dates or len(set(dates)) > 1:
            decisions["date"].record("validation", "rejected", "Invalid or conflicting dates")
        else:
            decisions["date"].record("dateparser", "accepted", "Explicit date phrase normalized using reference", dates[0])
    return decisions


def normalize_candidate(entity: dict, text: str, reference: datetime):
    start, end = entity.get("start"), entity.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(text):
        return None
    if entity.get("text") != text[start:end]:
        return None
    if start and text[start - 1].isalnum() and text[start].isalnum():
        return None
    if end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
        return None
    value = text[start:end].strip()
    name = entity.get("candidate_field")
    if name == "amount":
        # Models sometimes omit a minus sign from their predicted span.
        if re.search(r"[-−]\s*(?:(?:S\$|\$|SGD)\s*)?$", text[:start], re.I):
            return None
        if re.match(r"(?i)\s+(?:days?|weeks?|months?|years?|coffees?|cups?|items?|people|friends)\b", text[end:]):
            return None
        value = re.sub(r"(?i)^(?:S\$|\$|SGD)\s*", "", value)
        value = re.sub(r"(?i)\s*(?:bucks?|dollars?|SGD)$", "", value)
        return _parse_money(value.strip())
    if name == "date":
        return normalize_date(value, reference)
    if name == "merchant":
        # Restore a possessive only when it is literally adjacent in the input.
        if text[end:end + 2] in ("'s", "’s"):
            value += text[end:end + 2]
        return value if valid_merchant(value) else None
    return None


def apply_model(decisions, entities, text, reference, layer):
    for name, decision in decisions.items():
        if decision.state not in ("missing", "uncertain"):
            continue
        candidates = [item for item in entities if item.get("candidate_field") == name]
        values = []
        for candidate in candidates:
            value = normalize_candidate(candidate, text, reference)
            if value is not None:
                values.append((value, candidate))
        unique = {value for value, _ in values}
        if len(unique) > 1:
            decision.record(layer, "rejected", "Conflicting valid model candidates")
        elif len(unique) == 1:
            value, _ = values[0]
            acceptable = layer == "spacy" or any(
                item.get("score", 0) >= GLINER_ACCEPT_THRESHOLD for _, item in values
            )
            if acceptable:
                decision.record(layer, "accepted", "Unique candidate passed span and field checks", value)
            else:
                decision.record(layer, "uncertain", "Candidate below GLiNER acceptance threshold")
        else:
            decision.record(layer, decision.state, "No acceptable candidate")


def run_layers(text: str, reference: datetime, *, use_models: bool = True):
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ValueError("reference_datetime must include a timezone offset")
    decisions = rule_decisions(text, reference)
    attempted = []
    if use_models and text:
        for layer, predict in (("spacy", extract_spacy_entities), ("gliner", extract_gliner_entities)):
            if not any(item.state in ("missing", "uncertain") for item in decisions.values()):
                break
            try:
                with _MODEL_LOCK:
                    entities = predict(text)
            except Exception as exc:
                raise ModelUnavailableError(f"The {layer} layer could not run; check model installation and server logs") from exc
            attempted.append({"layer": layer, "candidates": entities})
            apply_model(decisions, entities, text, reference, layer)

    values = {name: item.value for name, item in decisions.items()}
    missing = [name for name, value in values.items() if value is None]
    result = ExtractResponse(**values, status="incomplete" if missing else "ok", missing_fields=missing)
    trace = {name: asdict(item) for name, item in decisions.items()}
    for item in trace.values():
        if isinstance(item["value"], date):
            item["value"] = item["value"].isoformat()
    return result, {"fields": trace, "model_attempts": attempted}
