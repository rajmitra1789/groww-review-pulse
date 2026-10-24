"""Free-text PII scan and the quote-pool name heuristic."""

from __future__ import annotations

import re

# Product and brand words. They do not count as a person's name.
PRODUCT_WORDS = frozenset(
    {
        "amc",
        "android",
        "apple",
        "axis",
        "bank",
        "bse",
        "demat",
        "elss",
        "etf",
        "fno",
        "fund",
        "funds",
        "google",
        "gpay",
        "groww",
        "gst",
        "hdfc",
        "icici",
        "inr",
        "ios",
        "ipo",
        "kotak",
        "kyc",
        "mutual",
        "nav",
        "nifty",
        "nse",
        "pan",
        "paytm",
        "phonepe",
        "play",
        "sbi",
        "sebi",
        "sensex",
        "sip",
        "store",
        "upi",
        "upstox",
        "whatsapp",
        "zerodha",
    }
)

PRODUCT_PHRASES = frozenset(
    {
        "f&o",
        "google play",
        "google play store",
        "mutual fund",
        "mutual funds",
        "play store",
    }
)

SIGN_OFF_WORDS = (
    "thank you",
    "thanks",
    "warm regards",
    "kind regards",
    "best regards",
    "regards",
    "yours sincerely",
    "yours truly",
    "sincerely",
    "cheers",
    "yours",
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_UPI = re.compile(r"(?<![\w.])[A-Za-z][A-Za-z0-9._-]{1,}@[A-Za-z]{2,64}(?![\w.])")
_HANDLE = re.compile(r"(?<![\w.])@[A-Za-z0-9_]{2,}")
_PHONE = re.compile(r"(?<!\d)(?:\+91[\s-]*)?(?:0[\s-]*)?(?:\d[\s-]*){10}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_DIGITS = re.compile(r"(?<!\d)\d{8,}(?!\d)")
_NAME_IS = re.compile(r"(?i)\bmy name is\s+[A-Za-z]+")
_TOKEN = re.compile(r"[A-Za-z]+")
_START = re.compile(
    r"^\s*"
    r"([A-Z][A-Za-z]+)"
    r"(?:\s+([A-Z][A-Za-z]+))?"
    r"(?:\s*,|\s*:|\s+[Hh]ere\b)"
)
_SIGN_OFF = re.compile(
    r"(?:%s)\s*,?\s+([A-Za-z]{2,})(?:\s+([A-Za-z]{2,}))?\s*[.!]?\s*$"
    % "|".join(re.escape(word) for word in sorted(SIGN_OFF_WORDS, key=len, reverse=True)),
    re.IGNORECASE,
)
_INITIALS = re.compile(r"([A-Za-z]{2,})\s+([A-Za-z])(?:\s+([A-Za-z]))?\s*[.!]?\s*$")

_PATTERNS = (
    ("email", _EMAIL),
    ("upi", _UPI),
    ("handle", _HANDLE),
    ("phone", _PHONE),
    ("pan", _PAN),
    ("digit_run", _DIGITS),
    ("self_id", _NAME_IS),
)


def find_pii(text: str) -> tuple[str, ...]:
    """Return the PII kinds found in ``text``. Empty when the text is clean."""
    if not text:
        return ()
    found: list[str] = []
    occupied: list[tuple[int, int]] = []
    for kind, pattern in _PATTERNS:
        matched = False
        for match in pattern.finditer(text):
            span = match.span()
            if any(start < span[1] and span[0] < end for start, end in occupied):
                continue
            occupied.append(span)
            matched = True
        if matched:
            found.append(kind)
    return tuple(found)


def looks_like_name(text: str) -> bool:
    """True when the text appears to contain a person's name.

    Errs toward dropping. Product and brand words do not count.
    """
    if not text:
        return False
    return (
        _start_name(text)
        or _consecutive_names(text)
        or _signature(text)
        or _sign_off_name(text)
    )


def _start_name(text: str) -> bool:
    match = _START.match(text)
    if not match:
        return False
    words = [match.group(1)]
    if match.group(2):
        words.append(match.group(2))
    return any(word.casefold() not in PRODUCT_WORDS for word in words)


def _consecutive_names(text: str) -> bool:
    matches = list(_TOKEN.finditer(text))
    for left, right in zip(matches, matches[1:]):
        gap = text[left.end() : right.start()]
        if not gap.isspace():
            continue
        first, second = left.group(), right.group()
        if not _capitalised(first) or not _capitalised(second):
            continue
        if _is_sentence_start(text, left.start()):
            continue
        if first.casefold() in PRODUCT_WORDS or second.casefold() in PRODUCT_WORDS:
            continue
        if f"{first} {second}".casefold() in PRODUCT_PHRASES:
            continue
        return True
    return False


def _signature(text: str) -> bool:
    match = _INITIALS.search(text)
    if not match:
        return False
    word = match.group(1)
    return _capitalised(word) and word.casefold() not in PRODUCT_WORDS


def _sign_off_name(text: str) -> bool:
    match = _SIGN_OFF.search(text)
    if not match:
        return False
    words = [match.group(1)]
    if match.group(2):
        words.append(match.group(2))
    if not all(_capitalised(word) for word in words):
        return False
    return any(word.casefold() not in PRODUCT_WORDS for word in words)


def _capitalised(word: str) -> bool:
    return len(word) >= 2 and word[0].isupper() and word.isalpha()


def _is_sentence_start(text: str, index: int) -> bool:
    prefix = text[:index]
    if not prefix.strip():
        return True
    return bool(re.search(r"(?:[.!?]\s*|\n+)\s*$", prefix))
