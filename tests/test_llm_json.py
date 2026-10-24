from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from groq import RateLimitError

from pulse.llm import JSON_RETRY_SUFFIX, call_json
from pulse.note import ComposeError, QuoteCandidate, parse_compose_result


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.messages: list[object] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        self.messages.append(kwargs.get("messages"))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))]
        )


def _rate_limit(retry_after: str = "0") -> RateLimitError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(
        429,
        headers={"retry-after": retry_after},
        request=request,
    )
    return RateLimitError("rate limited", response=response, body=None)


def _pool() -> tuple[QuoteCandidate, ...]:
    return (
        QuoteCandidate(
            id="aaaaaaaaaaaa",
            theme="Charges",
            text="Brokerage charges on every trade are far too high now",
            thumbs_up=3,
            distance=0.1,
        ),
        QuoteCandidate(
            id="bbbbbbbbbbbb",
            theme="Support",
            text="Customer support never answers the ticket after many tries",
            thumbs_up=2,
            distance=0.2,
        ),
        QuoteCandidate(
            id="cccccccccccc",
            theme="Charts",
            text="The charts freeze whenever the market opens each morning",
            thumbs_up=1,
            distance=0.3,
        ),
    )


def _compose_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "themes": [
            {"rank": 1, "line": "Users complain about brokerage charges."},
            {"rank": 2, "line": "Support tickets go unanswered."},
            {"rank": 3, "line": "Charts freeze at market open."},
        ],
        "quote_ids": ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"],
        "actions": [
            {"theme_rank": 1, "text": "Review brokerage on small orders."},
            {"theme_rank": 2, "text": "Staff the in-app support queue."},
            {"theme_rank": 3, "text": "Fix chart loading at open."},
        ],
    }
    payload.update(overrides)
    return payload


def test_valid_json_is_parsed() -> None:
    client = FakeClient(['{"name": "Brokerage Charges"}'])
    result = call_json("system", "user", client=client)
    assert result == {"name": "Brokerage Charges"}
    assert client.calls == 1


def test_invalid_json_triggers_exactly_one_retry() -> None:
    client = FakeClient(["not json", '{"ok": true}'])
    result = call_json("system", "user", client=client)
    assert result == {"ok": True}
    assert client.calls == 2
    retry_user = client.messages[1][1]["content"]
    assert JSON_RETRY_SUFFIX in retry_user


def test_unknown_quote_id_is_rejected() -> None:
    with pytest.raises(ComposeError, match="unknown quote ID"):
        parse_compose_result(
            _compose_payload(quote_ids=["aaaaaaaaaaaa", "bbbbbbbbbbbb", "deadbeefdead"]),
            _pool(),
        )


def test_rate_limit_waits_once_then_retries() -> None:
    client = FakeClient([_rate_limit("0"), '{"ok": true}'])
    slept: list[float] = []
    result = call_json("system", "user", client=client, sleep=slept.append)
    assert result == {"ok": True}
    assert client.calls == 2
    assert slept == [0.0]
