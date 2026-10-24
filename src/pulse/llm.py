"""Groq JSON calls: one retry on invalid JSON, one wait on HTTP 429."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

from groq import RateLimitError

from pulse.config import GROQ_MODEL, get_setting

TEMPERATURE = 0.2
JSON_RETRY_SUFFIX = "return JSON only"

SleepFn = Callable[[float], None]

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def call_json(
    system: str,
    user: str,
    schema_hint: str = "",
    *,
    client=None,
    sleep: SleepFn | None = None,
) -> dict:
    """Call the model and parse one JSON object.

    Invalid JSON is retried once. A 429 waits for ``retry-after`` and is retried once.
    """
    groq_client = client or _default_client()
    sleep_fn = sleep or time.sleep
    rate_retried = False
    json_retried = False
    remind = False

    while True:
        messages = _messages(system, user, schema_hint, remind)
        try:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                temperature=TEMPERATURE,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except RateLimitError as exc:
            if rate_retried:
                raise
            rate_retried = True
            sleep_fn(_retry_after_seconds(exc))
            continue
        content = response.choices[0].message.content or ""
        try:
            return _parse_json_object(content)
        except ValueError:
            if json_retried:
                raise
            json_retried = True
            remind = True


def _default_client():
    from groq import Groq

    api_key = get_setting("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    return Groq(api_key=api_key)


def _messages(system: str, user: str, schema_hint: str, remind: bool) -> list[dict[str, str]]:
    parts = [user]
    if schema_hint:
        parts.append(f"JSON schema: {schema_hint}")
    if remind:
        parts.append(JSON_RETRY_SUFFIX)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(parts)},
    ]


def _parse_json_object(raw: str) -> dict:
    text = _FENCE_RE.sub("", raw.strip()).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("response is not JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON must be an object")
    return value


def _retry_after_seconds(exc: RateLimitError) -> float:
    header = exc.response.headers.get("retry-after", "").strip()
    if not header:
        return 1.0
    try:
        return max(0.0, float(header))
    except ValueError:
        parsed = parsedate_to_datetime(header)
        if parsed is None:
            return 1.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        wait = (parsed - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, wait)
