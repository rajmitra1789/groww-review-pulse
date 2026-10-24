from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from pulse.models import Review
from pulse.pipeline import run_pulse
from pulse.snapshot import write_snapshot

WEEK = date(2026, 10, 18)
_TOPICS = (
    "The brokerage charges on every trade are far too high for small orders",
    "Customer support never answers the ticket and the chat keeps dropping calls",
    "The charts freeze and the indicators lag whenever the market opens each day",
)


def _hex_id(index: int) -> str:
    return f"{index:012x}"


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


def _many_reviews(count: int = 36) -> list[Review]:
    reviews: list[Review] = []
    for index in range(count):
        text = _TOPICS[index % len(_TOPICS)]
        reviews.append(_review(text, _hex_id(index), rating=1 + (index % 5)))
    return reviews


def _embed(texts: list[str]) -> np.ndarray:
    vectors = np.zeros((len(texts), 8), dtype=np.float32)
    for row, text in enumerate(texts):
        lowered = text.lower()
        if "brokerage" in lowered or "charge" in lowered:
            vectors[row, 0] = 1.0
        if "support" in lowered or "ticket" in lowered:
            vectors[row, 1] = 1.0
        if "chart" in lowered or "indicator" in lowered:
            vectors[row, 2] = 1.0
        vectors[row, 5] = (sum(map(ord, lowered)) % 7) / 7.0
    return vectors


class FakeLLM:
    def __init__(self, compose_builder, compose_times: int = 1) -> None:
        self.compose_builder = compose_builder
        self.compose_times = compose_times
        self.labels = 0
        self.compose_calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: object) -> SimpleNamespace:
        messages = kwargs["messages"]  # type: ignore[index]
        user = messages[1]["content"]
        if "Draft the note pieces" in user:
            self.compose_calls += 1
            payload = self.compose_builder(user, self.compose_calls)
            content = json.dumps(payload)
        else:
            self.labels += 1
            content = json.dumps(
                {
                    "name": f"Theme {self.labels}",
                    "summary": "Users mention this topic often",
                }
            )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _quote_ids(user: str) -> list[str]:
    for line in user.splitlines():
        if line.startswith("{") and "quotes" in line:
            body = json.loads(line)
            return [item["id"] for item in body["quotes"][:3]]
    raise AssertionError("compose prompt had no quote pool")


def _good_compose(user: str, _call: int) -> dict[str, object]:
    ids = _quote_ids(user)
    return {
        "themes": [
            {"rank": 1, "line": "Users complain about brokerage charges."},
            {"rank": 2, "line": "Support tickets go unanswered."},
            {"rank": 3, "line": "Charts freeze at market open."},
        ],
        "quote_ids": ids,
        "actions": [
            {"theme_rank": 1, "text": "Review brokerage on small orders."},
            {"theme_rank": 2, "text": "Staff the in-app support queue."},
            {"theme_rank": 3, "text": "Fix chart loading at open."},
        ],
    }


def _bad_compose(user: str, _call: int) -> dict[str, object]:
    payload = _good_compose(user, _call)
    payload["actions"] = [
        {"theme_rank": 1, "text": "Hire 999 extra agents for charges."},
        {"theme_rank": 2, "text": "Staff the in-app support queue."},
        {"theme_rank": 3, "text": "Fix chart loading at open."},
    ]
    return payload


def _run(tmp_path: Path, reviews: list[Review], client: FakeLLM) -> object:
    snapshot = tmp_path / "snapshot.jsonl"
    write_snapshot(snapshot, reviews)
    return run_pulse(
        snapshot,
        week_ending=WEEK,
        run_dir=tmp_path / "run",
        client=client,
        embed_fn=_embed,
    )


def test_run_that_passes(tmp_path: Path) -> None:
    client = FakeLLM(_good_compose)
    result = _run(tmp_path, _many_reviews(), client)
    assert result.passed
    assert result.stop_reason == ""
    assert client.compose_calls == 1
    run_dir = tmp_path / "run"
    for name in ("reviews.jsonl", "funnel.json", "themes.json", "note.md", "checks.json"):
        assert (run_dir / name).exists()
    assert result.zip_path is not None and result.zip_path.exists()


def test_run_that_fails_twice_stops(tmp_path: Path) -> None:
    client = FakeLLM(_bad_compose)
    result = _run(tmp_path, _many_reviews(), client)
    assert not result.passed
    assert client.compose_calls == 2
    assert any(item.check == "Grounded numbers" for item in result.failures)


def test_run_with_too_few_reviews(tmp_path: Path) -> None:
    client = FakeLLM(_good_compose)
    result = _run(tmp_path, _many_reviews(5), client)
    assert result.stop_reason == "not enough reviews for a pulse"
    assert result.note == ""
    assert client.labels == 0
    assert client.compose_calls == 0
