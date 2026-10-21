"""Snapshot schema for a Play Store review with reviewer identity removed."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pulse.config import TIMEZONE

_IST = ZoneInfo(TIMEZONE)


@dataclass(frozen=True)
class Review:
    id: str
    rating: int
    title: str | None
    text: str
    date: date
    app_version: str | None
    thumbs_up: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "rating": self.rating,
            "title": self.title,
            "text": self.text,
            "date": self.date.isoformat(),
            "app_version": self.app_version,
            "thumbs_up": self.thumbs_up,
        }

    @classmethod
    def from_play(cls, raw: dict) -> Review:
        """Map a google-play-scraper review. Identity fields are dropped."""
        review_id = raw.get("reviewId")
        if not isinstance(review_id, str) or not review_id:
            raise ValueError("reviewId is missing")

        score = raw.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            raise ValueError("score must be an integer from 1 to 5")

        text = raw.get("content")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise ValueError("content must be a string")

        at = raw.get("at")
        if not isinstance(at, datetime):
            raise ValueError("at must be a datetime")

        thumbs = raw.get("thumbsUpCount", 0)
        if thumbs is None:
            thumbs = 0
        if isinstance(thumbs, bool) or not isinstance(thumbs, int) or thumbs < 0:
            raise ValueError("thumbsUpCount must be a non-negative integer")

        app_version = raw.get("appVersion")
        if app_version is not None and not isinstance(app_version, str):
            raise ValueError("appVersion must be a string or null")
        if app_version == "":
            app_version = None

        return cls(
            id=_hash_review_id(review_id),
            rating=score,
            title=None,
            text=text,
            date=_to_ist_date(at),
            app_version=app_version,
            thumbs_up=thumbs,
        )


def _hash_review_id(review_id: str) -> str:
    return hashlib.sha256(review_id.encode("utf-8")).hexdigest()[:12]


def _to_ist_date(at: datetime) -> date:
    if at.tzinfo is None:
        at = at.astimezone()
    return at.astimezone(_IST).date()
