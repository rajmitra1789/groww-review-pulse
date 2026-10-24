"""Pure review filters and the Phase 2 funnel."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import emoji
from lingua import Language, LanguageDetectorBuilder

from pulse.config import (
    MIN_ENGLISH_CONFIDENCE,
    MIN_WORDS,
    TIMEZONE,
    WINDOW_WEEKS,
)
from pulse.models import Review

_IST = ZoneInfo(TIMEZONE)
_WORD_RE = re.compile(r"\w+")
_DETECTOR_LANGUAGES = (
    Language.ENGLISH,
    Language.HINDI,
    Language.BENGALI,
    Language.TAMIL,
    Language.TELUGU,
    Language.MARATHI,
    Language.GUJARATI,
    Language.PUNJABI,
    Language.URDU,
)
_detector = None

# Title is empty in Play snapshots and is never used for filtering.


@dataclass(frozen=True)
class Funnel:
    reviews_in: int
    removed_by_window: int
    removed_by_emoji_only: int
    removed_by_word_count: int
    removed_by_language: int
    reviews_kept: int

    def to_dict(self) -> dict[str, int]:
        return {
            "reviews_in": self.reviews_in,
            "removed_by_window": self.removed_by_window,
            "removed_by_emoji_only": self.removed_by_emoji_only,
            "removed_by_word_count": self.removed_by_word_count,
            "removed_by_language": self.removed_by_language,
            "reviews_kept": self.reviews_kept,
        }

    @classmethod
    def from_dict(cls, row: dict) -> Funnel:
        return cls(
            reviews_in=int(row["reviews_in"]),
            removed_by_window=int(row["removed_by_window"]),
            removed_by_emoji_only=int(row["removed_by_emoji_only"]),
            removed_by_word_count=int(row["removed_by_word_count"]),
            removed_by_language=int(row["removed_by_language"]),
            reviews_kept=int(row["reviews_kept"]),
        )


def last_full_sunday(today: date | None = None) -> date:
    """Most recent Sunday on or before `today` in IST (the last full week end)."""
    if today is None:
        today = datetime.now(_IST).date()
    days_since_sunday = (today.weekday() + 1) % 7
    return today - timedelta(days=days_since_sunday)


def window_bounds(week_ending: date, window_weeks: int = WINDOW_WEEKS) -> tuple[date, date]:
    _check_window_weeks(window_weeks)
    start = week_ending - timedelta(weeks=window_weeks) + timedelta(days=1)
    return start, week_ending


def in_window(
    review: Review,
    week_ending: date,
    window_weeks: int = WINDOW_WEEKS,
) -> bool:
    start, end = window_bounds(week_ending, window_weeks)
    return start <= review.date <= end


def is_emoji_only(text: str) -> bool:
    """True when no letter or digit remains after ignoring emoji, whitespace and punctuation."""
    without_emoji = emoji.replace_emoji(text, replace="")
    return not any(char.isalnum() for char in without_emoji)


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def has_enough_words(text: str, min_words: int = MIN_WORDS) -> bool:
    return word_count(text) >= min_words


def is_english(text: str, min_confidence: float = MIN_ENGLISH_CONFIDENCE) -> bool:
    values = _get_detector().compute_language_confidence_values(text)
    if not values:
        return False
    top = values[0]
    return top.language == Language.ENGLISH and top.value >= min_confidence


def apply_filters(
    reviews: list[Review],
    week_ending: date,
    window_weeks: int = WINDOW_WEEKS,
) -> tuple[list[Review], Funnel]:
    _check_window_weeks(window_weeks)
    reviews_in = len(reviews)

    after_window = [review for review in reviews if in_window(review, week_ending, window_weeks)]
    removed_by_window = reviews_in - len(after_window)

    after_emoji = [review for review in after_window if not is_emoji_only(review.text)]
    removed_by_emoji_only = len(after_window) - len(after_emoji)

    after_words = [review for review in after_emoji if has_enough_words(review.text)]
    removed_by_word_count = len(after_emoji) - len(after_words)

    after_language = _keep_english(after_words)
    removed_by_language = len(after_words) - len(after_language)

    funnel = Funnel(
        reviews_in=reviews_in,
        removed_by_window=removed_by_window,
        removed_by_emoji_only=removed_by_emoji_only,
        removed_by_word_count=removed_by_word_count,
        removed_by_language=removed_by_language,
        reviews_kept=len(after_language),
    )
    return after_language, funnel


def _keep_english(reviews: list[Review]) -> list[Review]:
    if not reviews:
        return []
    detector = _get_detector()
    values_list = detector.compute_language_confidence_values_in_parallel(
        [review.text for review in reviews]
    )
    kept: list[Review] = []
    for review, values in zip(reviews, values_list, strict=True):
        if (
            values
            and values[0].language == Language.ENGLISH
            and values[0].value >= MIN_ENGLISH_CONFIDENCE
        ):
            kept.append(review)
    return kept


def _get_detector():
    global _detector
    if _detector is None:
        _detector = LanguageDetectorBuilder.from_languages(*_DETECTOR_LANGUAGES).build()
    return _detector


def _check_window_weeks(window_weeks: int) -> None:
    if not 8 <= window_weeks <= 12:
        raise ValueError("window_weeks must be between 8 and 12")
