"""Download public Play Store reviews into a PII-stripped snapshot."""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google_play_scraper import Sort
from google_play_scraper import reviews as fetch_page

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse.config import (  # noqa: E402
    APP_ID,
    PLAY_COUNTRY,
    PLAY_LANG,
    SNAPSHOTS_DIR,
    TIMEZONE,
    WINDOW_WEEKS,
)
from pulse.models import Review  # noqa: E402
from pulse.snapshot import write_snapshot  # noqa: E402

PAGE_SIZE = 200
PAGE_SLEEP_SECONDS = 2
MAX_PAGE_RETRIES = 3


def _today_ist() -> date:
    return datetime.now(ZoneInfo(TIMEZONE)).date()


def _cutoff_date() -> date:
    return _today_ist() - timedelta(weeks=WINDOW_WEEKS + 1)


def _fetch_one_page(continuation_token: object) -> tuple[list[dict], object]:
    last_error: Exception | None = None
    for attempt in range(1, MAX_PAGE_RETRIES + 1):
        try:
            return fetch_page(
                APP_ID,
                lang=PLAY_LANG,
                country=PLAY_COUNTRY,
                sort=Sort.NEWEST,
                count=PAGE_SIZE,
                continuation_token=continuation_token,
            )
        except Exception as exc:  # noqa: BLE001 — retry Play Store transport errors
            last_error = exc
            wait = PAGE_SLEEP_SECONDS * attempt
            print(
                f"  request failed ({type(exc).__name__}); "
                f"retry {attempt}/{MAX_PAGE_RETRIES} in {wait}s"
            )
            time.sleep(wait)
    assert last_error is not None
    raise last_error


def fetch_reviews() -> list[Review]:
    cutoff = _cutoff_date()
    collected: list[Review] = []
    continuation_token = None
    page_number = 0
    skipped = 0
    reached_cutoff = False

    print(
        f"Fetching {APP_ID} reviews ({PLAY_LANG}/{PLAY_COUNTRY}), "
        f"newest first, until before {cutoff.isoformat()} "
        f"({WINDOW_WEEKS}+1 weeks). Pausing {PAGE_SLEEP_SECONDS}s between pages."
    )

    while not reached_cutoff:
        page_number += 1
        if page_number > 1:
            print(f"Pausing {PAGE_SLEEP_SECONDS}s before page {page_number}.")
            time.sleep(PAGE_SLEEP_SECONDS)

        print(f"Fetching page {page_number} ({PAGE_SIZE} reviews)...")
        raw_page, continuation_token = _fetch_one_page(continuation_token)
        if not raw_page:
            print(f"  page {page_number} returned no reviews; stopping.")
            break

        kept_this_page = 0
        oldest_this_page: date | None = None
        for raw in raw_page:
            try:
                review = Review.from_play(raw)
            except (TypeError, ValueError):
                skipped += 1
                continue
            if oldest_this_page is None or review.date < oldest_this_page:
                oldest_this_page = review.date
            if review.date < cutoff:
                reached_cutoff = True
                break
            collected.append(review)
            kept_this_page += 1

        oldest_label = oldest_this_page.isoformat() if oldest_this_page else "n/a"
        print(
            f"  got {len(raw_page)} reviews; kept {kept_this_page}; "
            f"oldest on page {oldest_label}."
        )

        if reached_cutoff:
            print(f"  reached cutoff {cutoff.isoformat()}; stopping.")
            break
        if continuation_token is None or getattr(continuation_token, "token", None) is None:
            print("  no continuation token; stopping.")
            break

    if skipped:
        print(f"Skipped {skipped} reviews that could not be mapped.")
    print(f"Fetched {page_number} page(s); {len(collected)} reviews in window.")
    return collected


def main() -> int:
    reviews = fetch_reviews()
    if not reviews:
        print("No reviews saved.")
        return 1

    snapshot_path = SNAPSHOTS_DIR / f"reviews_{_today_ist().isoformat()}.jsonl"
    write_snapshot(snapshot_path, reviews)
    dates = [review.date for review in reviews]
    print(f"Wrote {len(reviews)} reviews to {snapshot_path}")
    print(f"Oldest: {min(dates).isoformat()}")
    print(f"Newest: {max(dates).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
