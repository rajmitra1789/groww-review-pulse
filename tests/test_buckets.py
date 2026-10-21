from __future__ import annotations

from datetime import date

from pulse.buckets import (
    NOISE_GIBBERISH,
    NOISE_HINGLISH,
    NOISE_NON_LATIN,
    is_generic_praise,
    is_gibberish,
    is_hinglish,
    is_non_latin,
    split_buckets,
)
from pulse.models import Review


def _review(text: str, review_id: str = "aaaaaaaaaaaa") -> Review:
    return Review(
        id=review_id,
        rating=5,
        title=None,
        text=text,
        date=date(2026, 10, 1),
        app_version=None,
        thumbs_up=0,
    )


def test_hinglish_complaint_is_noise() -> None:
    text = "app bahut slow hai paisa nahi nikal raha please fix this now"
    assert is_hinglish(text)
    split = split_buckets([_review(text, "bbbbbbbbbbbb")])
    assert split.noise_reasons["bbbbbbbbbbbb"] == NOISE_HINGLISH
    assert len(split.clusterable) == 0


def test_romanised_punjabi_is_noise() -> None:
    text = "tusi eh app kiven use karde ho changa nahi lagda please fix karo"
    assert is_hinglish(text)
    split = split_buckets([_review(text, "cccccccccccc")])
    assert split.noise_reasons["cccccccccccc"] == NOISE_HINGLISH


def test_keyboard_mash_is_noise() -> None:
    text = "qw er ty ui op as df gh jk zx"
    assert is_gibberish(text)
    split = split_buckets([_review(text, "dddddddddddd")])
    assert split.noise_reasons["dddddddddddd"] == NOISE_GIBBERISH


def test_repeated_letter_spam_is_noise() -> None:
    text = "aaaaa bbbbb ccccc ddddd eeeee fffff"
    assert is_gibberish(text)
    split = split_buckets([_review(text, "eeeeeeeeeeee")])
    assert split.noise_reasons["eeeeeeeeeeee"] == NOISE_GIBBERISH


def test_non_latin_script_is_noise() -> None:
    text = "ಆಪ್ ತುಂಬಾ ನಿಧಾನವಾಗಿದೆ ದಯವಿಟ್ಟು ಇದನ್ನು ಸರಿಪಡಿಸಿ ಇದು ಕೆಲಸ ಮಾಡುತ್ತಿಲ್ಲ"
    assert is_non_latin(text)
    split = split_buckets([_review(text, "ffffffffffff")])
    assert split.noise_reasons["ffffffffffff"] == NOISE_NON_LATIN


def test_english_with_main_or_par_is_not_hinglish() -> None:
    text = (
        "The main reason I still use this platform is that withdrawals take too "
        "long after I par down a position over several days"
    )
    assert not is_hinglish(text)
    split = split_buckets([_review(text, "111111111111")])
    assert "111111111111" not in split.noise_reasons


def test_generic_praise_has_no_topic() -> None:
    text = "very easy to use, love it"
    assert is_generic_praise(text)
    split = split_buckets([_review(text, "222222222222")])
    assert [review.id for review in split.generic_praise] == ["222222222222"]
    assert split.clusterable == ()


def test_brokerage_complaint_is_clusterable() -> None:
    text = "good app but brokerage is too high"
    assert not is_generic_praise(text)
    split = split_buckets([_review(text, "333333333333")])
    assert [review.id for review in split.clusterable] == ["333333333333"]
    assert split.noise == ()
    assert split.generic_praise == ()


def test_split_buckets_records_topic_words_in_noise() -> None:
    hinglish = _review(
        "brokerage bahut high hai charges bhi jyada hota please dekh lo",
        "444444444444",
    )
    split = split_buckets([hinglish])
    summary = split.summary()
    assert summary.noise_count == 1
    assert "brokerage" in summary.noise_topic_words or "charges" in summary.noise_topic_words
