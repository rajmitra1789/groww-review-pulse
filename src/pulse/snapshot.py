"""Load and validate a JSONL or CSV snapshot of reviews."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from pulse.models import Review

SCHEMA_FIELDS = (
    "id",
    "rating",
    "title",
    "text",
    "date",
    "app_version",
    "thumbs_up",
)
FORBIDDEN_KEYS = frozenset(
    {"userName", "userImage", "reviewId", "replyContent", "repliedAt"}
)


class SnapshotError(ValueError):
    def __init__(self, message: str, line_number: int) -> None:
        super().__init__(f"line {line_number}: {message}")
        self.line_number = line_number
        self.message = message


def write_snapshot(path: Path, reviews: list[Review]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for review in reviews:
            handle.write(json.dumps(review.to_dict(), ensure_ascii=False) + "\n")


def load_snapshot(path: Path | str) -> list[Review]:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        raise FileNotFoundError(snapshot_path)
    suffix = snapshot_path.suffix.lower()
    if suffix == ".jsonl":
        return _load_jsonl(snapshot_path)
    if suffix == ".csv":
        return _load_csv(snapshot_path)
    raise SnapshotError(f"unsupported snapshot format: {suffix}", 0)


def _load_jsonl(path: Path) -> list[Review]:
    reviews: list[Review] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise SnapshotError(f"invalid JSON ({exc.msg})", line_number) from exc
            reviews.append(review_from_row(row, line_number))
    return reviews


def _load_csv(path: Path) -> list[Review]:
    reviews: list[Review] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_number, row in enumerate(reader, start=2):
            reviews.append(review_from_row(row, line_number))
    return reviews


def review_from_row(row: object, line_number: int) -> Review:
    if not isinstance(row, dict):
        raise SnapshotError("row is not an object", line_number)

    forbidden = sorted(FORBIDDEN_KEYS.intersection(row))
    if forbidden:
        raise SnapshotError(
            "identity fields present: " + ", ".join(forbidden), line_number
        )

    missing = [field for field in SCHEMA_FIELDS if field not in row]
    if missing:
        raise SnapshotError("missing fields: " + ", ".join(missing), line_number)

    review_id = _require_id(row["id"], line_number)
    rating = _require_rating(row["rating"], line_number)
    title = _optional_str(row["title"], "title", line_number)
    text = row["text"]
    if not isinstance(text, str):
        raise SnapshotError("text must be a string", line_number)
    review_date = _require_date(row["date"], line_number)
    app_version = _optional_str(row["app_version"], "app_version", line_number)
    thumbs_up = _require_thumbs(row["thumbs_up"], line_number)

    return Review(
        id=review_id,
        rating=rating,
        title=title,
        text=text,
        date=review_date,
        app_version=app_version,
        thumbs_up=thumbs_up,
    )


def _require_id(value: object, line_number: int) -> str:
    if not isinstance(value, str) or len(value) != 12:
        raise SnapshotError("id must be 12 hex characters", line_number)
    try:
        int(value, 16)
    except ValueError as exc:
        raise SnapshotError("id must be 12 hex characters", line_number) from exc
    if value != value.lower():
        raise SnapshotError("id must be 12 hex characters", line_number)
    return value


def _require_rating(value: object, line_number: int) -> int:
    rating = _as_int(value, "rating", line_number)
    if not 1 <= rating <= 5:
        raise SnapshotError("rating must be an integer from 1 to 5", line_number)
    return rating


def _require_thumbs(value: object, line_number: int) -> int:
    thumbs = _as_int(value, "thumbs_up", line_number)
    if thumbs < 0:
        raise SnapshotError("thumbs_up must be a non-negative integer", line_number)
    return thumbs


def _require_date(value: object, line_number: int) -> date:
    if not isinstance(value, str):
        raise SnapshotError("date must be an ISO date", line_number)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SnapshotError("date must be an ISO date", line_number) from exc


def _optional_str(value: object, field: str, line_number: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    raise SnapshotError(f"{field} must be a string or null", line_number)


def _as_int(value: object, field: str, line_number: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.isdigit():
            return int(value)
        raise SnapshotError(f"{field} must be an integer", line_number)
    return value
