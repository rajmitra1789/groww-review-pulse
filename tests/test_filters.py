from __future__ import annotations

from datetime import date

import pytest

from pulse.config import MIN_WORDS
from pulse.filters import (
    apply_filters,
    has_enough_words,
    in_window,
    is_emoji_only,
    is_english,
    last_full_sunday,
    window_bounds,
    word_count,
)
from pulse.models import Review


def _review(text: str, review_date: date = date(2026, 10, 1), review_id: str = "aaaaaaaaaaaa") -> Review:
    return Review(
        id=review_id,
        rating=4,
        title=None,
        text=text,
        date=review_date,
        app_version=None,
        thumbs_up=0,
    )


def test_last_full_sunday_from_wednesday() -> None:
    assert last_full_sunday(date(2026, 10, 21)) == date(2026, 10, 18)


def test_last_full_sunday_on_sunday_is_that_day() -> None:
    assert last_full_sunday(date(2026, 10, 18)) == date(2026, 10, 18)


def test_window_is_twelve_monday_to_sunday_weeks() -> None:
    start, end = window_bounds(date(2026, 10, 18), 12)
    assert start == date(2026, 7, 27)
    assert end == date(2026, 10, 18)
    assert in_window(_review("enough words here for the window check now", start), end, 12)
    assert in_window(_review("enough words here for the window check now", end), end, 12)
    assert not in_window(
        _review("enough words here for the window check now", date(2026, 7, 26)), end, 12
    )
    assert not in_window(
        _review("enough words here for the window check now", date(2026, 10, 19)), end, 12
    )


def test_emoji_only_reviews_are_dropped() -> None:
    assert is_emoji_only("👍👍👍")
    assert is_emoji_only("🔥🔥 !!!")
    assert is_emoji_only("   !!! ???")


def test_review_with_emoji_and_words_is_kept_unchanged() -> None:
    text = "Great app 👍 but withdrawals take 3 days"
    assert not is_emoji_only(text)
    long_text = "Great app 👍 but withdrawals take 3 days to complete now"
    assert word_count(long_text) >= MIN_WORDS
    review = _review(long_text)
    kept, funnel = apply_filters([review], week_ending=date(2026, 10, 18))
    assert funnel.reviews_kept == 1
    assert kept[0].text == long_text
    assert kept[0] is review


def test_word_count_boundary_and_emoji_are_not_words() -> None:
    eight = "one two three four five six seven eight"
    nine = "one two three four five six seven eight nine"
    assert word_count(eight) == 8
    assert word_count(nine) == 9
    assert not has_enough_words(eight)
    assert has_enough_words(nine)
    assert MIN_WORDS == 9
    assert word_count("Great 👍 app") == 2
    assert not has_enough_words("👍👍👍")


def test_english_kept_hindi_dropped() -> None:
    english = "This app is great for investing in mutual funds every day."
    hindi = "यह ऐप बहुत धीमा है और पैसा नहीं निकाला जा रहा है"
    hinglish = "app bahut slow hai paisa nahi nikal raha hai please fix"
    assert is_english(english)
    assert not is_english(hindi)
    # Latin-script Hinglish is ranked English by lingua; it is kept.
    assert is_english(hinglish)


def test_apply_filters_counts_each_rule_and_does_not_edit_text() -> None:
    week_ending = date(2026, 10, 18)
    original_text = "Great app 👍 but withdrawals take 3 days to complete now"
    reviews = [
        _review(original_text, date(2026, 10, 1), "aaaaaaaaaaaa"),
        _review("outside the twelve week window entirely here", date(2026, 7, 1), "bbbbbbbbbbbb"),
        _review("👍👍👍", date(2026, 10, 1), "cccccccccccc"),
        _review("too few words here now", date(2026, 10, 1), "dddddddddddd"),
        _review("यह ऐप बहुत धीमा है और पैसा नहीं निकाला जा रहा है", date(2026, 10, 1), "eeeeeeeeeeee"),
    ]
    kept, funnel = apply_filters(reviews, week_ending=week_ending, window_weeks=12)
    assert funnel.to_dict() == {
        "reviews_in": 5,
        "removed_by_window": 1,
        "removed_by_emoji_only": 1,
        "removed_by_word_count": 1,
        "removed_by_language": 1,
        "reviews_kept": 1,
    }
    assert funnel.reviews_in - (
        funnel.removed_by_window
        + funnel.removed_by_emoji_only
        + funnel.removed_by_word_count
        + funnel.removed_by_language
    ) == funnel.reviews_kept
    assert len(kept) == 1
    assert kept[0].id == "aaaaaaaaaaaa"
    assert kept[0].text == original_text
    assert kept[0].title is None


def test_window_weeks_must_be_8_to_12() -> None:
    review = _review("enough words here for the window check now")
    with pytest.raises(ValueError, match="window_weeks must be between 8 and 12"):
        apply_filters([review], week_ending=date(2026, 10, 18), window_weeks=7)
