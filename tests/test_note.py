from __future__ import annotations

from datetime import date

from pulse.filters import word_count
from pulse.models import Action, ComposeResult, PulseResult, Review, Theme, ThemeLine
from pulse.note import allowed_numbers, assemble, checks_from_failures, validate


WEEK = date(2026, 10, 18)


def _review(text: str, review_id: str, rating: int = 2) -> Review:
    return Review(
        id=review_id,
        rating=rating,
        title=None,
        text=text,
        date=date(2026, 10, 1),
        app_version=None,
        thumbs_up=1,
    )


def _theme(**overrides: object) -> Theme:
    values: dict[str, object] = {
        "cluster_id": 0,
        "name": "Charges",
        "summary": "Users complain about fees",
        "size": 40,
        "share_of_clusterable": 0.4,
        "share_of_kept": 0.2,
        "complaint_share": 0.8,
        "representative_ids": (),
        "member_ids": (),
        "centroid": (0.0, 0.0),
        "average_rating": 2.0,
        "one_two_star_share": 0.6,
    }
    values.update(overrides)
    return Theme(**values)  # type: ignore[arg-type]


def _reviews() -> list[Review]:
    return [
        _review("Brokerage charges on every trade are far too high now", "aaaaaaaaaaaa", 1),
        _review("Customer support never answers the ticket after many tries", "bbbbbbbbbbbb", 2),
        _review("The charts freeze whenever the market opens each morning", "cccccccccccc", 3),
    ]


def _themes() -> tuple[Theme, ...]:
    reviews = _reviews()
    return (
        _theme(
            cluster_id=0,
            name="Charges",
            member_ids=(reviews[0].id,),
            size=40,
            share_of_kept=0.20,
            average_rating=2.0,
        ),
        _theme(
            cluster_id=1,
            name="Support",
            member_ids=(reviews[1].id,),
            size=30,
            share_of_kept=0.15,
            average_rating=2.2,
        ),
        _theme(
            cluster_id=2,
            name="Charts",
            member_ids=(reviews[2].id,),
            size=20,
            share_of_kept=0.10,
            average_rating=2.4,
        ),
    )


def _compose(**overrides: object) -> ComposeResult:
    values: dict[str, object] = {
        "themes": (
            ThemeLine(1, "Users complain about brokerage charges."),
            ThemeLine(2, "Support tickets go unanswered."),
            ThemeLine(3, "Charts freeze at market open."),
        ),
        "quote_ids": ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"),
        "actions": (
            Action(1, "Review brokerage on small orders."),
            Action(2, "Staff the in-app support queue."),
            Action(3, "Fix chart loading at open."),
        ),
    }
    values.update(overrides)
    return ComposeResult(**values)  # type: ignore[arg-type]


def _result(note: str, compose: ComposeResult, reviews: list[Review], themes: tuple[Theme, ...]) -> PulseResult:
    allowed = allowed_numbers(
        note_week_ending=WEEK,
        window_weeks=12,
        reviews=reviews,
        themes=themes,
        compose=compose,
    )
    return PulseResult(
        week_ending=WEEK,
        window_weeks=12,
        window_start=date(2026, 7, 27),
        note=note,
        word_count=word_count(note),
        failures=(),
        checks=(),
        funnel=None,
        buckets=None,
        themes=themes,
        top_themes=themes,
        compose=compose,
        reviews=tuple(reviews),
        run_dir=None,  # type: ignore[arg-type]
        zip_path=None,
        k=3,
        silhouette=None,
        allowed_numbers=tuple(sorted(allowed)),
    )


def _assemble() -> tuple[str, ComposeResult, list[Review], tuple[Theme, ...]]:
    reviews = _reviews()
    themes = _themes()
    composed = _compose()
    note = assemble(themes, composed, reviews, week_ending=WEEK)
    return note, composed, reviews, themes


def test_passing_note() -> None:
    note, composed, reviews, themes = _assemble()
    failures = validate(note, _result(note, composed, reviews, themes))
    assert failures == []
    assert word_count(note) <= 250
    assert "12 Oct 2026" in note
    for review in reviews:
        assert f'"{review.text}" ({review.rating}★)' in note
        assert review.id not in note
    assert "2026-10-01" not in note


def test_length_failure() -> None:
    note, composed, reviews, themes = _assemble()
    note = note + "\n" + " ".join(["padding"] * 250)
    failures = validate(note, _result(note, composed, reviews, themes))
    assert [item.check for item in failures] == ["Length"]


def test_structure_failure() -> None:
    reviews = _reviews()
    themes = _themes()
    composed = _compose(actions=(Action(1, "Review brokerage on small orders."),))
    note = assemble(themes, composed, reviews, week_ending=WEEK)
    failures = validate(note, _result(note, composed, reviews, themes))
    assert "Structure" in [item.check for item in failures]


def test_verbatim_failure() -> None:
    note, composed, reviews, themes = _assemble()
    note = note.replace(reviews[0].text, "Invented wording about charges")
    failures = validate(note, _result(note, composed, reviews, themes))
    assert [item.check for item in failures] == ["Verbatim"]


def test_distinct_quotes_failure() -> None:
    reviews = _reviews()
    themes = _themes()
    composed = _compose(quote_ids=("aaaaaaaaaaaa", "aaaaaaaaaaaa", "cccccccccccc"))
    note = assemble(themes, composed, reviews, week_ending=WEEK)
    failures = validate(note, _result(note, composed, reviews, themes))
    assert "Distinct quotes" in [item.check for item in failures]


def test_grounded_numbers_failure() -> None:
    reviews = _reviews()
    themes = _themes()
    composed = _compose(
        actions=(
            Action(1, "Hire 999 extra agents for charges."),
            Action(2, "Staff the in-app support queue."),
            Action(3, "Fix chart loading at open."),
        )
    )
    note = assemble(themes, composed, reviews, week_ending=WEEK)
    failures = validate(note, _result(note, composed, reviews, themes))
    assert [item.check for item in failures] == ["Grounded numbers"]


def test_pii_failure() -> None:
    reviews = _reviews()
    themes = _themes()
    composed = _compose(
        themes=(
            ThemeLine(1, "Email users at help@example.com about charges."),
            ThemeLine(2, "Support tickets go unanswered."),
            ThemeLine(3, "Charts freeze at market open."),
        )
    )
    note = assemble(themes, composed, reviews, week_ending=WEEK)
    failures = validate(note, _result(note, composed, reviews, themes))
    assert [item.check for item in failures] == ["PII"]


def test_checks_cover_all_names() -> None:
    names = [item.check for item in checks_from_failures([])]
    assert names == [
        "Length",
        "Structure",
        "Verbatim",
        "Distinct quotes",
        "Grounded numbers",
        "PII",
    ]
