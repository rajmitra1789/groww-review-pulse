from __future__ import annotations

from datetime import date

import numpy as np

from pulse.models import Review, Theme
from pulse.note import build_quote_pool, quote_pool_payload
from pulse.themes import pick_top_themes


def _review(
    text: str,
    review_id: str,
    rating: int = 3,
    thumbs_up: int = 0,
) -> Review:
    return Review(
        id=review_id,
        rating=rating,
        title=None,
        text=text,
        date=date(2026, 10, 1),
        app_version=None,
        thumbs_up=thumbs_up,
    )


def _theme(**overrides: object) -> Theme:
    values: dict[str, object] = {
        "cluster_id": 0,
        "name": "Theme",
        "summary": "Users talk about this theme in reviews",
        "size": 10,
        "share_of_clusterable": 0.2,
        "share_of_kept": 0.1,
        "complaint_share": 0.8,
        "representative_ids": (),
        "member_ids": (),
        "centroid": (0.0, 0.0),
        "average_rating": 2.0,
        "one_two_star_share": 0.5,
    }
    values.update(overrides)
    return Theme(**values)  # type: ignore[arg-type]


def test_phone_number_never_enters_the_pool() -> None:
    review = _review(
        "Call me at 9876543210 because withdrawals take three days now",
        "111111111111",
    )
    theme = _theme(member_ids=(review.id,), name="Withdrawals")
    pool = build_quote_pool([theme], [review], {review.id: np.array([0.1, 0.0])})
    assert pool == ()


def test_likely_name_never_enters_the_pool() -> None:
    review = _review(
        "The support team and Rahul Sharma never answered my tickets this week",
        "222222222222",
    )
    theme = _theme(member_ids=(review.id,), name="Support")
    pool = build_quote_pool([theme], [review], {review.id: np.array([0.1, 0.0])})
    assert pool == ()


def test_name_like_signature_never_enters_the_pool() -> None:
    review = _review(
        "Withdrawals take three days after I sell my shares Yogeshwara m p",
        "333333333333",
    )
    theme = _theme(member_ids=(review.id,), name="Withdrawals")
    pool = build_quote_pool([theme], [review], {review.id: np.array([0.1, 0.0])})
    assert pool == ()


def test_forty_one_word_review_never_enters_the_pool() -> None:
    text = " ".join(["delayed"] * 41)
    review = _review(text, "444444444444")
    theme = _theme(member_ids=(review.id,), name="Withdrawals")
    pool = build_quote_pool([theme], [review], {review.id: np.array([0.1, 0.0])})
    assert pool == ()


def test_changing_only_star_ratings_does_not_change_ranking_or_pool() -> None:
    reviews = [
        _review("Brokerage charges on every trade are far too high now", "aaaaaaaaaaaa", rating=1),
        _review("Customer support never answers the ticket after many tries", "bbbbbbbbbbbb", rating=2),
        _review("The charts freeze whenever the market opens each morning", "cccccccccccc", rating=5),
    ]
    themes = [
        _theme(
            cluster_id=0,
            name="Charges",
            size=400,
            complaint_share=0.8,
            member_ids=("aaaaaaaaaaaa",),
        ),
        _theme(
            cluster_id=1,
            name="Support",
            size=300,
            complaint_share=0.7,
            member_ids=("bbbbbbbbbbbb",),
        ),
        _theme(
            cluster_id=2,
            name="Charts",
            size=200,
            complaint_share=0.6,
            member_ids=("cccccccccccc",),
        ),
    ]
    vectors = {
        "aaaaaaaaaaaa": np.array([0.1, 0.0]),
        "bbbbbbbbbbbb": np.array([0.1, 0.0]),
        "cccccccccccc": np.array([0.1, 0.0]),
    }
    flipped = [
        Review(
            id=review.id,
            rating=1 if review.rating >= 4 else 5,
            title=review.title,
            text=review.text,
            date=review.date,
            app_version=review.app_version,
            thumbs_up=review.thumbs_up,
        )
        for review in reviews
    ]
    original_top = pick_top_themes(themes, min_complaint_share=0.5)
    flipped_top = pick_top_themes(themes, min_complaint_share=0.5)
    assert [theme.cluster_id for theme in original_top] == [
        theme.cluster_id for theme in flipped_top
    ]
    original_pool = build_quote_pool(original_top, reviews, vectors)
    flipped_pool = build_quote_pool(flipped_top, flipped, vectors)
    assert [item.id for item in original_pool] == [item.id for item in flipped_pool]
    for item in quote_pool_payload(original_pool):
        assert set(item) == {"id", "theme", "text"}


def test_large_low_complaint_cluster_skipped_when_three_others_pass() -> None:
    themes = [
        _theme(cluster_id=0, name="Praise", size=500, complaint_share=0.2),
        _theme(cluster_id=1, name="Support", size=400, complaint_share=0.8),
        _theme(cluster_id=2, name="Charges", size=300, complaint_share=0.7),
        _theme(cluster_id=3, name="Withdrawals", size=200, complaint_share=0.9),
        _theme(cluster_id=4, name="Charts", size=100, complaint_share=0.6),
    ]
    top = pick_top_themes(themes, min_complaint_share=0.5)
    assert [theme.cluster_id for theme in top] == [1, 2, 3]


def test_large_low_complaint_cluster_fills_when_fewer_than_three_pass() -> None:
    themes = [
        _theme(cluster_id=0, name="Praise", size=500, complaint_share=0.2),
        _theme(cluster_id=1, name="Support", size=80, complaint_share=0.9),
        _theme(cluster_id=2, name="Charges", size=40, complaint_share=0.8),
        _theme(cluster_id=3, name="Generic", size=200, complaint_share=0.1),
        _theme(cluster_id=4, name="Noise", size=10, complaint_share=0.0),
    ]
    top = pick_top_themes(themes, min_complaint_share=0.5)
    assert [theme.cluster_id for theme in top] == [1, 2, 0]
