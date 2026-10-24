"""Quote pool and the compose call. Assembly belongs to Phase 5."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from pulse.config import QUOTE_WORDS
from pulse.filters import word_count
from pulse.llm import call_json
from pulse.models import Action, ComposeResult, Theme, ThemeLine
from pulse.pii import find_pii, looks_like_name

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
) -> ComposeResult:
    """Ask for theme lines, quote ids and actions. Unknown quote ids are rejected."""
    payload = call_json(
        COMPOSE_SYSTEM,
        _compose_user(themes, pool),
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


def _compose_user(themes: Sequence[Theme], pool: Sequence[QuoteCandidate]) -> str:
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
    return (
        "Draft the note pieces from this input. "
        "Each action theme_rank is 1, 2 or 3.\n"
        + json.dumps(body, ensure_ascii=False)
    )


def _distance(vector: np.ndarray | None, centroid: Sequence[float]) -> float:
    if vector is None:
        return float("inf")
    point = np.asarray(vector, dtype=np.float64)
    center = np.asarray(centroid, dtype=np.float64)
    return float(np.linalg.norm(point - center))
