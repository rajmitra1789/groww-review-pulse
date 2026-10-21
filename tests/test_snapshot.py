from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from pulse.models import Review
from pulse.snapshot import SnapshotError, load_snapshot, write_snapshot


def _raw_review(**overrides: object) -> dict:
    raw = {
        "reviewId": "gp:test-review-id-001",
        "userName": "Jane Doe",
        "userImage": "https://lh3.googleusercontent.com/a/example",
        "content": "Great app for investing in mutual funds daily.",
        "score": 5,
        "thumbsUpCount": 3,
        "at": datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc),
        "replyContent": "Thanks for the feedback",
        "repliedAt": datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc),
        "appVersion": "1.2.3",
    }
    raw.update(overrides)
    return raw


def test_from_play_strips_identity_fields() -> None:
    review = Review.from_play(_raw_review())
    payload = review.to_dict()

    assert set(payload) == {
        "id",
        "rating",
        "title",
        "text",
        "date",
        "app_version",
        "thumbs_up",
    }
    for forbidden in (
        "userName",
        "userImage",
        "reviewId",
        "replyContent",
        "repliedAt",
    ):
        assert forbidden not in payload
        assert forbidden not in json.dumps(payload)

    expected_id = hashlib.sha256(b"gp:test-review-id-001").hexdigest()[:12]
    assert review.id == expected_id
    assert len(review.id) == 12
    int(review.id, 16)
    assert review.title is None
    assert review.rating == 5
    assert review.app_version == "1.2.3"
    assert review.thumbs_up == 3
    assert "http" not in json.dumps(payload).lower()


def test_from_play_converts_date_to_ist() -> None:
    # 2026-10-01 20:00 UTC is 2026-10-02 01:30 in Asia/Kolkata.
    review = Review.from_play(
        _raw_review(at=datetime(2026, 10, 1, 20, 0, 0, tzinfo=timezone.utc))
    )
    assert review.date == date(2026, 10, 2)


def test_load_jsonl_round_trip(tmp_path: Path) -> None:
    review = Review.from_play(_raw_review())
    path = tmp_path / "reviews.jsonl"
    write_snapshot(path, [review])
    loaded = load_snapshot(path)
    assert loaded == [review]


def test_load_csv(tmp_path: Path) -> None:
    path = tmp_path / "reviews.csv"
    path.write_text(
        "id,rating,title,text,date,app_version,thumbs_up\n"
        "aaaaaaaaaaaa,4,,Saved for later,2026-10-01,,2\n",
        encoding="utf-8",
    )
    loaded = load_snapshot(path)
    assert len(loaded) == 1
    assert loaded[0].id == "aaaaaaaaaaaa"
    assert loaded[0].rating == 4
    assert loaded[0].title is None
    assert loaded[0].text == "Saved for later"
    assert loaded[0].date == date(2026, 10, 1)
    assert loaded[0].app_version is None
    assert loaded[0].thumbs_up == 2


def test_bad_jsonl_row_reports_line_number(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    good = Review.from_play(_raw_review()).to_dict()
    bad = {**good, "rating": "high"}
    path.write_text(
        json.dumps(good) + "\n" + json.dumps(bad) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SnapshotError, match="line 2: rating must be an integer") as exc:
        load_snapshot(path)
    assert exc.value.line_number == 2


def test_identity_fields_in_snapshot_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    row = Review.from_play(_raw_review()).to_dict()
    row["userName"] = "Jane Doe"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(SnapshotError, match="line 1: identity fields present: userName"):
        load_snapshot(path)
