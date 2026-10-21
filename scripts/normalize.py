"""Apply Phase 2 filters and write reviews.jsonl plus funnel.json."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse.config import RUNS_DIR, WINDOW_WEEKS  # noqa: E402
from pulse.filters import apply_filters, last_full_sunday  # noqa: E402
from pulse.snapshot import load_snapshot, write_snapshot  # noqa: E402


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a Play Store snapshot.")
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument(
        "--week-ending",
        type=_parse_date,
        default=None,
        help="Inclusive window end (ISO date). Defaults to the last full Sunday IST.",
    )
    parser.add_argument("--window-weeks", type=int, default=WINDOW_WEEKS)
    args = parser.parse_args()

    week_ending = args.week_ending or last_full_sunday()
    reviews = load_snapshot(args.snapshot)
    kept, funnel = apply_filters(
        reviews, week_ending=week_ending, window_weeks=args.window_weeks
    )

    run_dir = RUNS_DIR / week_ending.isoformat()
    run_dir.mkdir(parents=True, exist_ok=True)
    reviews_path = run_dir / "reviews.jsonl"
    funnel_path = run_dir / "funnel.json"
    write_snapshot(reviews_path, kept)
    funnel_path.write_text(json.dumps(funnel.to_dict(), indent=2) + "\n", encoding="utf-8")

    after_window = funnel.reviews_in - funnel.removed_by_window
    after_emoji = after_window - funnel.removed_by_emoji_only
    after_words = after_emoji - funnel.removed_by_word_count
    after_language = after_words - funnel.removed_by_language

    print(f"week_ending {week_ending.isoformat()}")
    print(f"reviews in {funnel.reviews_in}")
    print(f"removed by window {funnel.removed_by_window} after {after_window}")
    print(f"removed by emoji-only {funnel.removed_by_emoji_only} after {after_emoji}")
    print(f"removed by word count {funnel.removed_by_word_count} after {after_words}")
    print(f"removed by language {funnel.removed_by_language} after {after_language}")
    print(f"reviews kept {funnel.reviews_kept}")
    print(f"wrote {reviews_path}")
    print(f"wrote {funnel_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
