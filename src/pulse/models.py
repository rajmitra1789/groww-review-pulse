"""Snapshot schema for a Play Store review with reviewer identity removed."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
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


@dataclass(frozen=True)
class Buckets:
    kept_count: int
    noise_count: int
    noise_reason_counts: dict[str, int]
    generic_praise_count: int
    clusterable_count: int
    noise_topic_words: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "kept_count": self.kept_count,
            "noise_count": self.noise_count,
            "noise_reason_counts": dict(self.noise_reason_counts),
            "generic_praise_count": self.generic_praise_count,
            "clusterable_count": self.clusterable_count,
            "noise_topic_words": dict(self.noise_topic_words),
        }


@dataclass(frozen=True)
class Cluster:
    id: int
    member_ids: tuple[str, ...]
    centroid: tuple[float, ...]
    size: int
    share_of_clusterable: float
    share_of_kept: float
    complaint_share: float
    top_topic_words: tuple[str, ...]
    representative_ids: tuple[str, ...]
    average_rating: float
    one_two_star_share: float

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "member_ids": list(self.member_ids),
            "centroid": [float(value) for value in self.centroid],
            "size": self.size,
            "share_of_clusterable": self.share_of_clusterable,
            "share_of_kept": self.share_of_kept,
            "complaint_share": self.complaint_share,
            "top_topic_words": list(self.top_topic_words),
            "representative_ids": list(self.representative_ids),
            "average_rating": self.average_rating,
            "one_two_star_share": self.one_two_star_share,
        }

    @classmethod
    def from_dict(cls, row: dict) -> Cluster:
        return cls(
            id=int(row["id"]),
            member_ids=tuple(row["member_ids"]),
            centroid=tuple(float(value) for value in row["centroid"]),
            size=int(row["size"]),
            share_of_clusterable=float(row["share_of_clusterable"]),
            share_of_kept=float(row["share_of_kept"]),
            complaint_share=float(row["complaint_share"]),
            top_topic_words=tuple(row.get("top_topic_words") or ()),
            representative_ids=tuple(row["representative_ids"]),
            average_rating=float(row["average_rating"]),
            one_two_star_share=float(row["one_two_star_share"]),
        )


@dataclass(frozen=True)
class Theme:
    cluster_id: int
    name: str
    summary: str
    size: int
    share_of_clusterable: float
    share_of_kept: float
    complaint_share: float
    representative_ids: tuple[str, ...]
    member_ids: tuple[str, ...]
    centroid: tuple[float, ...]
    average_rating: float
    one_two_star_share: float
    top_topic_words: tuple[str, ...] = ()

    @classmethod
    def from_cluster(cls, cluster: Cluster, name: str, summary: str) -> Theme:
        return cls(
            cluster_id=cluster.id,
            name=name,
            summary=summary,
            size=cluster.size,
            share_of_clusterable=cluster.share_of_clusterable,
            share_of_kept=cluster.share_of_kept,
            complaint_share=cluster.complaint_share,
            representative_ids=cluster.representative_ids,
            member_ids=cluster.member_ids,
            centroid=cluster.centroid,
            average_rating=cluster.average_rating,
            one_two_star_share=cluster.one_two_star_share,
            top_topic_words=cluster.top_topic_words,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "cluster_id": self.cluster_id,
            "name": self.name,
            "summary": self.summary,
            "size": self.size,
            "share_of_clusterable": self.share_of_clusterable,
            "share_of_kept": self.share_of_kept,
            "complaint_share": self.complaint_share,
            "representative_ids": list(self.representative_ids),
            "member_ids": list(self.member_ids),
            "centroid": [float(value) for value in self.centroid],
            "average_rating": self.average_rating,
            "one_two_star_share": self.one_two_star_share,
            "top_topic_words": list(self.top_topic_words),
        }


@dataclass(frozen=True)
class ThemeLine:
    rank: int
    line: str


@dataclass(frozen=True)
class Action:
    theme_rank: int
    text: str


@dataclass(frozen=True)
class ComposeResult:
    themes: tuple[ThemeLine, ...]
    quote_ids: tuple[str, ...]
    actions: tuple[Action, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "themes": [{"rank": item.rank, "line": item.line} for item in self.themes],
            "quote_ids": list(self.quote_ids),
            "actions": [
                {"theme_rank": item.theme_rank, "text": item.text} for item in self.actions
            ],
        }


@dataclass(frozen=True)
class Failure:
    check: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"check": self.check, "detail": self.detail}


@dataclass(frozen=True)
class CheckResult:
    check: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"check": self.check, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class PulseResult:
    week_ending: date
    window_weeks: int
    window_start: date
    note: str
    word_count: int
    failures: tuple[Failure, ...]
    checks: tuple[CheckResult, ...]
    funnel: object
    buckets: Buckets | None
    themes: tuple[Theme, ...]
    top_themes: tuple[Theme, ...]
    compose: ComposeResult | None
    reviews: tuple[Review, ...]
    run_dir: Path
    zip_path: Path | None
    k: int
    silhouette: float | None
    allowed_numbers: tuple[str, ...] = ()
    stop_reason: str = ""

    @property
    def passed(self) -> bool:
        return not self.failures and not self.stop_reason


def _hash_review_id(review_id: str) -> str:
    return hashlib.sha256(review_id.encode("utf-8")).hexdigest()[:12]


def _to_ist_date(at: datetime) -> date:
    if at.tzinfo is None:
        at = at.astimezone()
    return at.astimezone(_IST).date()
