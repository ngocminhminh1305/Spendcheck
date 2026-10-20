"""Rule-based entity extraction for Spendcheck Module 1."""

import re
import math
from datetime import date, datetime

from dateparser.search import search_dates


# Prefer explicit money markers because they are the strongest signal.
_NUMBER = r"[+-]?\d[\d,]*(?:\.\d+)?"
_CURRENCY_AMOUNT = re.compile(
    rf"(?ix)(?<!\w)([+-]?\s*(?:S\$|\$|SGD)\s*{_NUMBER})(?![\w.])"
)

# Also support casual input such as "5 bucks" or "paid 4.25".
_SUFFIX_AMOUNT = re.compile(
    rf"(?ix)(?<![\w./-])({_NUMBER})\s*(?:bucks?|dollars?|sgd)\b"
)
_BARE_NUMBER = re.compile(rf"(?<![\w.,/+-])({_NUMBER})(?![\w.,/+-])")
_TRANSACTION_SIGNAL = re.compile(
    r"(?ix)\b(?:spent|spend|paid|pay|cost|bought|buy|purchase|ordered?|"
    r"today|yesterday|tomorrow|ago)\b"
)
_MONTH_NEXT_TO_NUMBER = re.compile(
    r"(?ix)\b(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b"
)
_NOT_MONEY = re.compile(
    r"(?ix)\b\d+\s+(?:days?|weeks?|months?|years?|coffees?|cups?|items?|people)\b"
)
_VALID_MONEY = re.compile(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?")

_DATE_SIGNAL = re.compile(
    r"(?ix)"
    r"\b(?:today|yesterday|tomorrow|ago|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|september|"
    r"october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b"
    r"|\b\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,4})?\b"
)
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

_MERCHANT_AFTER_BUY = re.compile(r"(?ix)\b(?:buy|bought|ordered?)\s+(.+)$")
_SUBSCRIPTION_START = re.compile(r"(?i)\bsubscrib(?:e|ed|ing)\s+(?:to\s+)?(.+)$")
_MERCHANT_BEFORE_AMOUNT = re.compile(
    r"(?ix)^\s*(.+?)\s+(?=(?:S\$|\$|SGD\s*)?\d+(?:\.\d{1,2})?\b)"
)
_MERCHANT_AFTER_AMOUNT = re.compile(
    r"(?ix)(?:S\$|\$|SGD\s*)?\d+(?:,\d{3})*(?:\.\d{1,2})?\s+(.+)$"
)
_MERCHANT_STOP = re.compile(
    r"(?ix)\s+(?="
    r"(?:S\$|\$|SGD\s*)?\d+(?:,\d{3})*(?:\.\d{1,2})?\b|"
    r"today\b|yesterday\b|tomorrow\b|"
    r"(?:one|two|three|four|five|six|seven|\d+)\s+days?\s+ago\b|"
    r"last\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|"
    r"this\s+(?:morning|afternoon|evening|night)\b|"
    r"for\s+(?:S\$|\$|SGD\s*)?\d|"
    r"on\s+(?:\d|january|february|march|april|may|june|july|august|"
    r"september|october|november|december)"
    r")"
)
_NON_MERCHANT_WORDS = {
    "at",
    "buy",
    "bought",
    "from",
    "on",
    "order",
    "ordered",
    "paid",
    "pay",
    "spent",
    "spend",
    "to",
    "today",
    "tomorrow",
    "yesterday",
    "breakfast", "lunch", "dinner", "coffee", "food", "groceries",
    "premium", "subscription", "membership", "plan",
}


def find_amount_candidates(text: str) -> list[str]:
    """Keep candidate text even when invalid, so later layers cannot revive it."""
    explicit = list(_CURRENCY_AMOUNT.finditer(text))
    # Do not count "SGD 8 dollars" twice.
    explicit += [
        match for match in _SUFFIX_AMOUNT.finditer(text)
        if not any(match.start() < other.end() and other.start() < match.end()
                   for other in explicit)
    ]
    if explicit:
        if len(explicit) != 1 or re.search(r"(?i)\bor\s+[+-]?\d", text):
            return [match.group(1) for match in explicit] + ["ambiguous"]
        return [re.sub(r"(?i)S\$|\$|SGD", "", explicit[0].group(1)).strip()]

    # Bare numbers need transaction context or a compact "merchant amount"
    # entry. Exclude years, quantities and date components before accepting.
    if _TRANSACTION_SIGNAL.search(text) or _MERCHANT_BEFORE_AMOUNT.match(text):
        candidates = []
        excluded = list(_NOT_MONEY.finditer(text))
        for match in _BARE_NUMBER.finditer(text):
            if any(other.start() <= match.start() < other.end() for other in excluded):
                continue
            value = float(match.group(1).replace(",", ""))
            nearby_text = text[max(0, match.start() - 12) : match.end() + 12]
            if 1900 <= value <= 2100 or _MONTH_NEXT_TO_NUMBER.search(nearby_text):
                continue
            candidates.append(match.group(1).strip())
        return candidates

    return []


def extract_amount(text: str) -> float | None:
    """Accept one supported money candidate; abstain on competing amounts."""
    candidates = find_amount_candidates(text)
    if len(candidates) == 1:
        return _parse_money(candidates[0])

    return None


def _parse_money(raw: str) -> float | None:
    """Reject invalid formatting, negatives, zero, and non-finite values."""
    if not _VALID_MONEY.fullmatch(raw):
        return None
    value = float(raw.replace(",", ""))
    return value if math.isfinite(value) and value > 0 else None


def has_multiple_transactions(text: str) -> bool:
    """Detect clear separate purchases, without treating every 'and' as one."""
    clauses = re.split(r"(?i)\s+and\s+|;", text)
    purchases = [
        clause for clause in clauses
        if extract_amount(clause) is not None and extract_merchant(clause) is not None
    ]
    return len(purchases) > 1


def extract_date(text: str, reference_datetime: datetime) -> date | None:
    """Extract a date relative to a caller-provided point in time."""
    text = re.sub(
        r"(?i)\bthis (?:morning|afternoon|evening|night)\b", "today", text
    )
    iso_match = _ISO_DATE.search(text)
    if iso_match:
        try:
            return date.fromisoformat(iso_match.group(1))
        except ValueError:
            return None

    matches = search_dates(
        text,
        languages=["en"],
        settings={
            "RELATIVE_BASE": reference_datetime,
            "PREFER_DATES_FROM": "past",
            "DATE_ORDER": "DMY",
        },
    )

    if not matches:
        return None

    for matched_text, parsed_datetime in matches:
        # dateparser can interpret plain numbers as dates. Require a date-like
        # word or separator so an amount such as "8.90" is not mistaken for one.
        if _DATE_SIGNAL.search(matched_text):
            return parsed_datetime.date()

    return None


def extract_subscription_provider(text: str) -> str | None:
    """Extract a subscription provider; remove trailing plan descriptors only here."""
    match = _SUBSCRIPTION_START.search(text)
    if not match:
        return None
    provider = _MERCHANT_STOP.split(match.group(1), maxsplit=1)[0].strip(" ,.;:!?")
    provider = re.sub(
        r"(?i)\s+(?:premium|subscription|membership|plan)"
        r"(?:\s+(?:subscription|membership|plan))*$", "", provider,
    ).strip()
    if not provider or provider.casefold() in _NON_MERCHANT_WORDS:
        return None
    return provider


# Spendcheck integration change: rides such as "grab to school 14.60" or "taxi to airport 30".
# Without this, "to" is read as "paid to <merchant>" and the destination ("school", "airport")
# became the merchant. The ride provider or mode at the start of the entry is the merchant.
_TRIP = re.compile(
    r"(?ix)^\s*(?:(?:took|take|taking|booked|book)\s+(?:a\s+)?)?"
    r"(grab|gojek|tada|ryde|zig|cdg|comfortdelgro|taxi|cab|uber|bus|mrt|train)"
    r"(?:\s+(?:ride|car|trip|share))?\s+(?:to|from)\s+\S"
)


def extract_trip_provider(text: str) -> str | None:
    """The ride provider in "<ride> to/from <place> <amount>" entries, spelled as typed."""
    match = _TRIP.match(text)
    return match.group(1) if match else None


def extract_merchant(text: str) -> str | None:
    """Extract a merchant using common transaction sentence patterns."""
    candidates: list[str] = []
    provider = extract_subscription_provider(text)
    if provider:
        candidates.append(provider)
    trip_provider = extract_trip_provider(text)   # integration change, see _TRIP
    if trip_provider:
        candidates.append(trip_provider)

    # Try each marker, so an earlier date phrase does not hide "at Kopitiam".
    for marker in re.finditer(r"(?i)\b(?:at|from|to|on)\s+", text):
        candidates.append(text[marker.end():])

    buy_match = _MERCHANT_AFTER_BUY.search(text)
    if buy_match:
        candidates.append(buy_match.group(1))

    leading_match = _MERCHANT_BEFORE_AMOUNT.search(text)
    if leading_match:
        candidates.append(leading_match.group(1))

    after_amount_match = _MERCHANT_AFTER_AMOUNT.search(text)
    if after_amount_match:
        candidates.append(after_amount_match.group(1))

    for candidate in candidates:
        merchant = _MERCHANT_STOP.split(candidate, maxsplit=1)[0]
        merchant = merchant.strip(" \t\n,.;:!?-")

        # A merchant must contain at least one letter; this rejects date-only
        # candidates such as "on 05/10/2026".
        if (
            merchant
            and re.search(r"[A-Za-z]", merchant)
            and merchant.casefold() not in _NON_MERCHANT_WORDS
            and not re.match(r"(?i)^(?:at|from|to|on)\b", merchant)
            and not _DATE_SIGNAL.search(merchant)
            and not re.search(r"(?i)\b(?:spent|paid|buy|bought|for|or|and)\b", merchant)
        ):
            return merchant

    return None
