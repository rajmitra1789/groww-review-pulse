"""Quote pool, compose call, note assembly and validation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from pulse.config import MAX_NOTE_WORDS, QUOTE_WORDS, WINDOW_WEEKS
from pulse.filters import window_bounds, word_count
from pulse.llm import call_json
from pulse.models import Action, CheckResult, ComposeResult, Failure, Review, Theme, ThemeLine
from pulse.pii import find_pii, looks_like_name

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
CHECK_NAMES = (
    "Length",
    "Structure",
    "Verbatim",
    "Distinct quotes",
    "Grounded numbers",
    "PII",
)

QUOTES_PER_THEME = 8

COMPOSE_SYSTEM = (
    "You draft three theme lines, three quote ids and three actions for a weekly review note. "
    "Return JSON only. Pick quote ids only from the quote pool. "
    "Use one quote per theme where possible. "
    "Each action is something a product, growth or support team could do. "
    "Do not add numbers that are not in the input. "
    "Never invent a duration, hour, percentage, count, or service target."
)
COMPOSE_SCHEMA = (
    '{"themes": [{"rank": 1, "line": "..."}, {"rank": 2, "line": "..."}, {"rank": 3, "line": "..."}], '
    '"quote_ids": ["id", "id", "id"], '
    '"actions": [{"theme_rank": 1, "text": "..."}, {"theme_rank": 2, "text": "..."}, '
    '{"theme_rank": 3, "text": "..."}]}'
)


class ComposeError(ValueError):
    """The compose JSON failed a shape check."""


@dataclass(frozen=True)
class QuoteCandidate:
    id: str
    theme: str
    text: str
    thumbs_up: int
    distance: float

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "theme": self.theme, "text": self.text}


def build_quote_pool(
    themes: Sequence[Theme],
    reviews: Sequence,
    vectors_by_id: Mapping[str, np.ndarray],
    *,
    per_theme: int = QUOTES_PER_THEME,
) -> tuple[QuoteCandidate, ...]:
    """Candidates for the top themes: 9 to 40 words, no PII, no likely name.

    For each theme, keep the ``per_theme`` reviews nearest the centroid, then
    rank that shortlist by ``thumbs_up``. Star ratings are not used.
    """
    by_id = {review.id: review for review in reviews}
    low, high = QUOTE_WORDS
    pool: list[QuoteCandidate] = []
    for theme in themes:
        near: list[tuple[float, str, object]] = []
        for review_id in theme.member_ids:
            review = by_id.get(review_id)
            if review is None:
                continue
            if not low <= word_count(review.text) <= high:
                continue
            if find_pii(review.text) or looks_like_name(review.text):
                continue
            distance = _distance(vectors_by_id.get(review_id), theme.centroid)
            near.append((distance, review.id, review))
        near.sort(key=lambda item: (item[0], item[1]))
        shortlist = near[:per_theme]
        shortlist.sort(key=lambda item: (-item[2].thumbs_up, item[0], item[1]))
        for distance, _, review in shortlist:
            pool.append(
                QuoteCandidate(
                    id=review.id,
                    theme=theme.name,
                    text=review.text,
                    thumbs_up=review.thumbs_up,
                    distance=distance,
                )
            )
    return tuple(pool)


def quote_pool_payload(pool: Sequence[QuoteCandidate]) -> list[dict[str, str]]:
    """Quote candidates as sent to the model: id, theme and text only."""
    return [candidate.to_dict() for candidate in pool]


def compose(
    themes: Sequence[Theme],
    pool: Sequence[QuoteCandidate],
    *,
    client=None,
    failures: Sequence[Failure] = (),
) -> ComposeResult:
    """Ask for theme lines, quote ids and actions. Unknown quote ids are rejected."""
    payload = call_json(
        COMPOSE_SYSTEM,
        _compose_user(themes, pool, failures),
        COMPOSE_SCHEMA,
        client=client,
    )
    return parse_compose_result(payload, pool)


def parse_compose_result(payload: dict, pool: Sequence[QuoteCandidate]) -> ComposeResult:
    """Validate the compose JSON. An id outside the pool is an error."""
    theme_rows = payload.get("themes")
    quote_ids = payload.get("quote_ids")
    action_rows = payload.get("actions")
    if not isinstance(theme_rows, list) or len(theme_rows) != 3:
        raise ComposeError("compose result needs 3 theme lines")
    if not isinstance(quote_ids, list) or len(quote_ids) != 3:
        raise ComposeError("compose result needs 3 quote ids")
    if not isinstance(action_rows, list) or len(action_rows) != 3:
        raise ComposeError("compose result needs 3 actions")

    lines: list[ThemeLine] = []
    ranks: list[int] = []
    for row in theme_rows:
        if not isinstance(row, dict):
            raise ComposeError("theme line must be an object")
        rank = row.get("rank")
        line = row.get("line")
        if rank not in (1, 2, 3) or not isinstance(line, str) or not line.strip():
            raise ComposeError("theme line needs rank 1, 2 or 3 and a line")
        ranks.append(rank)
        lines.append(ThemeLine(rank=rank, line=line.strip()))
    if sorted(ranks) != [1, 2, 3]:
        raise ComposeError("theme ranks must be 1, 2 and 3")
    lines.sort(key=lambda item: item.rank)

    if any(not isinstance(quote_id, str) for quote_id in quote_ids):
        raise ComposeError("quote ids must be strings")
    if len(set(quote_ids)) != 3:
        raise ComposeError("quote ids must be distinct")
    pool_ids = {candidate.id for candidate in pool}
    for quote_id in quote_ids:
        if quote_id not in pool_ids:
            raise ComposeError(f"unknown quote ID: {quote_id}")

    actions: list[Action] = []
    for row in action_rows:
        if not isinstance(row, dict):
            raise ComposeError("action must be an object")
        theme_rank = row.get("theme_rank")
        text = row.get("text")
        if theme_rank not in (1, 2, 3) or not isinstance(text, str) or not text.strip():
            raise ComposeError("action needs theme_rank 1, 2 or 3 and text")
        actions.append(Action(theme_rank=theme_rank, text=text.strip()))

    return ComposeResult(themes=tuple(lines), quote_ids=tuple(quote_ids), actions=tuple(actions))


def assemble(
    themes: Sequence[Theme],
    compose_result: ComposeResult,
    reviews: Sequence[Review],
    *,
    week_ending: date,
    window_weeks: int = WINDOW_WEEKS,
) -> str:
    """Build the note from the template. Quote text is copied by id."""
    by_id = {review.id: review for review in reviews}
    start, end = window_bounds(week_ending, window_weeks)
    week_of = week_ending - timedelta(days=6)
    kept = len(reviews)
    average = _mean_rating(reviews)
    lines_by_rank = {item.rank: item.line for item in compose_result.themes}

    theme_lines = ["Top themes"]
    for rank, theme in enumerate(themes, start=1):
        share = _percent(theme.share_of_kept)
        line = lines_by_rank.get(rank, theme.summary)
        theme_lines.append(
            f"{rank}. {theme.name} ({share}% of reviews, avg {theme.average_rating:.1f}★): {line}"
        )

    quote_lines = ["What users said"]
    for quote_id in compose_result.quote_ids:
        review = by_id[quote_id]
        quote_lines.append(f'"{review.text}" ({review.rating}★)')

    action_lines = ["What to do next"]
    for index, action in enumerate(compose_result.actions, start=1):
        theme = themes[action.theme_rank - 1]
        action_lines.append(f"{index}. {action.text}  [{theme.name}]")

    header = (
        f"Groww Review Pulse - week of {_format_day(week_of)}\n"
        f"{kept} Play Store reviews, {_format_day(start)} to {_format_day(end)}. "
        f"Average rating {average:.1f}."
    )
    return "\n".join([header, "", *theme_lines, "", *quote_lines, "", *action_lines]) + "\n"


def validate(note: str, result) -> list[Failure]:
    """Run the six required checks. ``result`` is a PulseResult (or compatible)."""
    failures: list[Failure] = []
    compose = result.compose
    reviews = tuple(result.reviews)
    themes = tuple(result.top_themes)
    allowed = set(result.allowed_numbers) if result.allowed_numbers else allowed_numbers(
        note_week_ending=result.week_ending,
        window_weeks=result.window_weeks,
        reviews=reviews,
        themes=themes,
        compose=compose,
    )

    count = word_count(note)
    if count > MAX_NOTE_WORDS:
        failures.append(
            Failure("Length", f"{count} words; at most {MAX_NOTE_WORDS} allowed")
        )

    structure = _structure_failure(compose, themes)
    if structure:
        failures.append(structure)

    if compose is not None:
        by_id = {review.id: review for review in reviews}
        for quote_id in compose.quote_ids:
            review = by_id.get(quote_id)
            if review is None or review.text not in note:
                failures.append(
                    Failure("Verbatim", "a quote is not an exact substring of its review")
                )
                break
        if len(set(compose.quote_ids)) != 3:
            failures.append(Failure("Distinct quotes", "quote ids are not all different"))

    unknown = sorted(_note_numbers(note) - allowed)
    if unknown:
        failures.append(
            Failure("Grounded numbers", "numbers not in the computed stats or template")
        )

    if find_pii(note):
        failures.append(Failure("PII", "the note contains a PII pattern"))

    return failures


def checks_from_failures(failures: Sequence[Failure]) -> tuple[CheckResult, ...]:
    failed = {item.check: item.detail for item in failures}
    return tuple(
        CheckResult(check=name, passed=name not in failed, detail=failed.get(name, ""))
        for name in CHECK_NAMES
    )


def allowed_numbers(
    *,
    note_week_ending: date,
    window_weeks: int,
    reviews: Sequence[Review],
    themes: Sequence[Theme],
    compose: ComposeResult | None,
) -> frozenset[str]:
    """Numbers that may appear in the note: template ranks, dates, and computed stats."""
    start, end = window_bounds(note_week_ending, window_weeks)
    week_of = note_week_ending - timedelta(days=6)
    values: set[str] = {"1", "2", "3"}
    _add_number(values, len(reviews))
    _add_number(values, _mean_rating(reviews))
    for day in (week_of, start, end, note_week_ending):
        _add_number(values, day.day)
        _add_number(values, day.year)
        _add_number(values, day.month)
    for theme in themes:
        _add_number(values, theme.size)
        _add_number(values, theme.share_of_kept)
        _add_number(values, theme.complaint_share)
        _add_number(values, theme.average_rating)
        _add_number(values, _percent(theme.share_of_kept))
        _add_number(values, _percent(theme.complaint_share))
        _add_number(values, theme.share_of_clusterable)
        _add_number(values, _percent(theme.share_of_clusterable))
        values.update(_note_numbers(theme.name))
        values.update(_note_numbers(theme.summary))
    if compose is not None:
        by_id = {review.id: review for review in reviews}
        for quote_id in compose.quote_ids:
            review = by_id.get(quote_id)
            if review is not None:
                _add_number(values, review.rating)
                values.update(_note_numbers(review.text))
    for review in reviews:
        _add_number(values, review.rating)
    return frozenset(values)


def _compose_user(
    themes: Sequence[Theme],
    pool: Sequence[QuoteCandidate],
    failures: Sequence[Failure] = (),
) -> str:
    body = {
        "themes": [
            {
                "rank": index,
                "name": theme.name,
                "summary": theme.summary,
                "review_count": theme.size,
                "complaint_share": theme.complaint_share,
                "share_of_kept": theme.share_of_kept,
            }
            for index, theme in enumerate(themes, start=1)
        ],
        "quotes": [candidate.to_dict() for candidate in pool],
    }
    parts = [
        "Draft the note pieces from this input. "
        "Each action theme_rank is 1, 2 or 3.",
        json.dumps(body, ensure_ascii=False),
    ]
    if failures:
        parts.append("Previous draft failed these checks:")
        parts.extend(f"- {item.check}: {item.detail}" for item in failures)
        parts.append("Return a corrected JSON object. Do not invent numbers.")
    return "\n".join(parts)


def _structure_failure(compose: ComposeResult | None, themes: Sequence[Theme]) -> Failure | None:
    if compose is None:
        return Failure("Structure", "compose result is missing")
    if len(themes) != 3:
        return Failure("Structure", "need exactly 3 top themes")
    if len(compose.themes) != 3 or len(compose.quote_ids) != 3 or len(compose.actions) != 3:
        return Failure("Structure", "need exactly 3 themes, 3 quotes and 3 actions")
    for action in compose.actions:
        if action.theme_rank not in (1, 2, 3) or action.theme_rank > len(themes):
            return Failure("Structure", "an action does not reference a top-3 theme")
    return None


def _mean_rating(reviews: Sequence[Review]) -> float:
    if not reviews:
        return 0.0
    return sum(review.rating for review in reviews) / len(reviews)


def _percent(share: float) -> int:
    return int(round(share * 100))


def _format_day(value: date) -> str:
    return f"{value.day} {value.strftime('%b')} {value.year}"


def _note_numbers(note: str) -> set[str]:
    return set(_NUMBER_RE.findall(note))


def _add_number(values: set[str], number: int | float) -> None:
    if isinstance(number, bool):
        return
    if isinstance(number, int):
        values.add(str(number))
        return
    values.add(f"{number:.1f}")
    values.add(f"{number:.2f}")
    values.add(f"{number:.3f}")
    rounded = round(number)
    values.add(str(int(rounded)))
    if number == int(number):
        values.add(str(int(number)))


def _distance(vector: np.ndarray | None, centroid: Sequence[float]) -> float:
    if vector is None:
        return float("inf")
    point = np.asarray(vector, dtype=np.float64)
    center = np.asarray(centroid, dtype=np.float64)
    return float(np.linalg.norm(point - center))
