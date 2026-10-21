"""Text-only split of kept reviews into noise, generic praise, and clusterable."""

from __future__ import annotations

import gzip
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pulse.models import Buckets, Review

_TOKEN_RE = re.compile(r"\w+")
_REPEAT_RE = re.compile(r"([A-Za-z])\1{4,}")
_WORDS_PATH = Path(__file__).resolve().parent / "data" / "english_words.txt.gz"

# Strong Roman-script Hindi / Punjabi / Telugu markers. Not English homographs.
STRONG_INDIC_WORDS = frozenset(
    {
        "aap",
        "aapka",
        "aapke",
        "aapko",
        "abhi",
        "acha",
        "acchi",
        "achi",
        "achcha",
        "achha",
        "apna",
        "apne",
        "apni",
        "baad",
        "badiya",
        "badhiya",
        "bagundi",
        "bahot",
        "bahut",
        "bakwaas",
        "bakwas",
        "bekaar",
        "bekar",
        "bhut",
        "bohot",
        "bura",
        "buri",
        "chahiye",
        "chahie",
        "chala",
        "chaala",
        "changa",
        "changi",
        "cheyandi",
        "diya",
        "enti",
        "faltu",
        "gatiya",
        "gaya",
        "gayi",
        "ghatiya",
        "hai",
        "hain",
        "hota",
        "hoti",
        "kaadu",
        "kabhi",
        "kahan",
        "kaise",
        "karna",
        "karne",
        "karo",
        "karta",
        "karte",
        "kiddan",
        "kithe",
        "kitna",
        "kitni",
        "kiven",
        "kiwe",
        "kiya",
        "kuch",
        "kya",
        "kyu",
        "kyuki",
        "kyunki",
        "kyun",
        "ledu",
        "ledhu",
        "lekin",
        "liya",
        "liye",
        "magar",
        "mera",
        "mere",
        "meri",
        "mujhe",
        "mujhko",
        "naal",
        "nahi",
        "nahin",
        "nai",
        "nhi",
        "paisa",
        "paise",
        "pareshan",
        "phir",
        "raha",
        "rahe",
        "rahi",
        "rha",
        "thoda",
        "tuhada",
        "tuhadi",
        "tusi",
        "undi",
        "undhi",
        "unnaru",
        "unnayi",
        "vich",
        "woh",
        "yeh",
        "zyada",
        "jyada",
    }
)

# Also English; count only toward the 25% Indic-token rule.
WEAK_INDIC_WORDS = frozenset({"main", "par", "pe", "ho"})

PRAISE_WORDS = frozenset(
    {
        "amazing",
        "appreciate",
        "appreciated",
        "awesome",
        "beautiful",
        "beginner",
        "beginners",
        "best",
        "brilliant",
        "clean",
        "comfortable",
        "convenient",
        "cool",
        "decent",
        "easy",
        "enjoy",
        "enjoyed",
        "excellent",
        "fabulous",
        "fantastic",
        "fast",
        "fine",
        "glad",
        "good",
        "great",
        "happy",
        "helpful",
        "impressive",
        "intuitive",
        "liked",
        "likes",
        "love",
        "loved",
        "loves",
        "loving",
        "lovely",
        "nice",
        "outstanding",
        "perfect",
        "pleasant",
        "pleased",
        "quick",
        "recommend",
        "recommended",
        "reliable",
        "satisfied",
        "seamless",
        "simple",
        "smooth",
        "solid",
        "super",
        "superb",
        "thank",
        "thanks",
        "trust",
        "trusted",
        "trustworthy",
        "useful",
        "wonderful",
        "wow",
    }
)

COMPLAINT_WORDS = frozenset(
    {
        "annoying",
        "blank",
        "blocked",
        "broke",
        "broken",
        "bug",
        "buggy",
        "bugs",
        "cannot",
        "cant",
        "cheat",
        "cheated",
        "cheating",
        "complicated",
        "confused",
        "confusing",
        "costly",
        "crash",
        "crashed",
        "crashes",
        "crashing",
        "deducted",
        "delay",
        "delayed",
        "delays",
        "didn",
        "difficult",
        "disappointed",
        "disappointing",
        "disgusting",
        "doesn",
        "dont",
        "error",
        "errors",
        "expensive",
        "fail",
        "failed",
        "failing",
        "failure",
        "fake",
        "force",
        "forced",
        "fraud",
        "freeze",
        "frozen",
        "frustrating",
        "frustrated",
        "garbage",
        "glitch",
        "glitches",
        "hang",
        "hanging",
        "hangs",
        "hate",
        "hated",
        "hidden",
        "horrible",
        "improve",
        "improvement",
        "improvements",
        "irritating",
        "irritation",
        "issue",
        "issues",
        "lag",
        "lags",
        "laggy",
        "loot",
        "looted",
        "loss",
        "losses",
        "lost",
        "misleading",
        "missing",
        "overpriced",
        "pathetic",
        "pending",
        "poor",
        "problem",
        "problems",
        "refund",
        "reject",
        "rejected",
        "reinstall",
        "robbed",
        "scam",
        "shame",
        "shameful",
        "slow",
        "slower",
        "steal",
        "stolen",
        "stuck",
        "stupid",
        "sucks",
        "terrible",
        "thief",
        "timeout",
        "trash",
        "unable",
        "uninstall",
        "uninstalled",
        "unreliable",
        "unstable",
        "unusable",
        "useless",
        "waste",
        "wont",
        "worse",
        "worst",
        "wrong",
        "bad",
    }
)

COMPLAINT_PHRASES = (
    "not working",
    "does not work",
    "doesn't work",
)

TOPIC_WORDS = frozenset(
    {
        "aadhaar",
        "aadhar",
        "ads",
        "advertisement",
        "analysis",
        "bond",
        "bonds",
        "broker",
        "brokerage",
        "brokers",
        "brokrage",
        "candle",
        "candlestick",
        "charge",
        "charged",
        "charges",
        "chart",
        "charts",
        "chatbot",
        "commission",
        "customer",
        "demat",
        "deposit",
        "derivative",
        "derivatives",
        "execution",
        "fd",
        "feature",
        "features",
        "fee",
        "fees",
        "fno",
        "futures",
        "gold",
        "gst",
        "helpline",
        "indicator",
        "indicators",
        "interface",
        "intraday",
        "ipo",
        "ipos",
        "kyc",
        "layout",
        "leverage",
        "login",
        "margin",
        "mtf",
        "navigation",
        "news",
        "notification",
        "notifications",
        "options",
        "order",
        "orders",
        "otp",
        "pledge",
        "portfolio",
        "redeem",
        "redemption",
        "referral",
        "research",
        "search",
        "sip",
        "sips",
        "slippage",
        "stoploss",
        "support",
        "tds",
        "ticket",
        "tutorial",
        "ui",
        "upi",
        "update",
        "updated",
        "updates",
        "ux",
        "version",
        "versions",
        "watchlist",
        "withdraw",
        "withdrawal",
        "withdrawals",
        "withdrawn",
    }
)

TOPIC_PHRASES = (
    "mutual fund",
    "mutual funds",
    "customer support",
    "customer service",
    "dark mode",
    "f&o",
    "f & o",
    "option chain",
    "stop loss",
    "square off",
    "hidden charge",
    "dp charge",
    "account opening",
    "order execution",
)

NOISE_NON_LATIN = "non_latin"
NOISE_GIBBERISH = "gibberish"
NOISE_HINGLISH = "hinglish"


@dataclass(frozen=True)
class BucketSplit:
    noise: tuple[Review, ...]
    generic_praise: tuple[Review, ...]
    clusterable: tuple[Review, ...]
    noise_reasons: dict[str, str]
    noise_topic_words: dict[str, int]

    def summary(self) -> Buckets:
        counts = Counter(self.noise_reasons.values())
        return Buckets(
            kept_count=len(self.noise) + len(self.generic_praise) + len(self.clusterable),
            noise_count=len(self.noise),
            noise_reason_counts={
                NOISE_NON_LATIN: int(counts.get(NOISE_NON_LATIN, 0)),
                NOISE_GIBBERISH: int(counts.get(NOISE_GIBBERISH, 0)),
                NOISE_HINGLISH: int(counts.get(NOISE_HINGLISH, 0)),
            },
            generic_praise_count=len(self.generic_praise),
            clusterable_count=len(self.clusterable),
            noise_topic_words=dict(self.noise_topic_words),
        )


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def is_non_latin(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for char in letters if not _is_latin_letter(char))
    return non_latin > len(letters) / 2


def is_gibberish(text: str) -> bool:
    letter_tokens = [token for token in tokenize(text) if token.isalpha()]
    if len(letter_tokens) < 5:
        return False
    short_share = sum(1 for token in letter_tokens if len(token) <= 2) / len(letter_tokens)
    english_3plus = sum(
        1 for token in letter_tokens if len(token) >= 3 and token in english_words()
    )
    if english_3plus / len(letter_tokens) >= 0.2:
        return False
    return short_share >= 0.6 or _REPEAT_RE.search(text) is not None


def is_hinglish(text: str) -> bool:
    tokens = tokenize(text)
    if not tokens:
        return False
    distinct_strong = {token for token in tokens if token in STRONG_INDIC_WORDS}
    if len(distinct_strong) >= 2:
        return True
    indic = sum(1 for token in tokens if token in STRONG_INDIC_WORDS or token in WEAK_INDIC_WORDS)
    return indic / len(tokens) >= 0.25


def has_praise_word(text: str) -> bool:
    return any(token in PRAISE_WORDS for token in tokenize(text))


def has_complaint_word(text: str) -> bool:
    tokens = tokenize(text)
    if any(token in COMPLAINT_WORDS for token in tokens):
        return True
    lowered = text.lower()
    return any(phrase in lowered for phrase in COMPLAINT_PHRASES)


def has_topic_word(text: str) -> bool:
    return bool(topic_hits(text))


def is_generic_praise(text: str) -> bool:
    return has_praise_word(text) and not has_complaint_word(text) and not has_topic_word(text)


def topic_hits(text: str) -> list[str]:
    hits = [token for token in tokenize(text) if token in TOPIC_WORDS]
    lowered = text.lower()
    for phrase in TOPIC_PHRASES:
        if phrase in lowered:
            hits.append(phrase.replace(" ", "_"))
    return hits


def split_buckets(reviews: list[Review]) -> BucketSplit:
    noise: list[Review] = []
    generic_praise: list[Review] = []
    clusterable: list[Review] = []
    noise_reasons: dict[str, str] = {}
    noise_topics: Counter[str] = Counter()

    for review in reviews:
        reason = _noise_reason(review.text)
        if reason is not None:
            noise.append(review)
            noise_reasons[review.id] = reason
            noise_topics.update(topic_hits(review.text))
            continue
        if is_generic_praise(review.text):
            generic_praise.append(review)
            continue
        clusterable.append(review)

    return BucketSplit(
        noise=tuple(noise),
        generic_praise=tuple(generic_praise),
        clusterable=tuple(clusterable),
        noise_reasons=noise_reasons,
        noise_topic_words=dict(noise_topics.most_common()),
    )


def _noise_reason(text: str) -> str | None:
    if is_non_latin(text):
        return NOISE_NON_LATIN
    if is_gibberish(text):
        return NOISE_GIBBERISH
    if is_hinglish(text):
        return NOISE_HINGLISH
    return None


def _is_latin_letter(char: str) -> bool:
    return "A" <= char <= "Z" or "a" <= char <= "z"


@lru_cache(maxsize=1)
def english_words() -> frozenset[str]:
    with gzip.open(_WORDS_PATH, "rt", encoding="utf-8") as handle:
        return frozenset(line.strip() for line in handle if line.strip())
