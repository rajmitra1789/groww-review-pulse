"""CLI preview of a weekly pulse. Delivery is not connected yet."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse.config import WINDOW_WEEKS  # noqa: E402
from pulse.filters import last_full_sunday  # noqa: E402
from pulse.pipeline import run_pulse  # noqa: E402


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a weekly review pulse preview.")
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--run", type=Path, default=None, help="Reuse a run folder from phases 2-3.")
    parser.add_argument("--week-ending", type=_parse_date, default=None)
    parser.add_argument("--window-weeks", type=int, default=WINDOW_WEEKS)
    args = parser.parse_args()

    if args.snapshot is None and args.run is None:
        parser.error("provide --snapshot or --run")

    week_ending = args.week_ending
    run_dir = args.run
    if run_dir is not None and week_ending is None:
        week_ending = date.fromisoformat(run_dir.name)

    result = run_pulse(
        args.snapshot,
        week_ending=week_ending or last_full_sunday(),
        window_weeks=args.window_weeks,
        run_dir=run_dir,
        reuse_run=run_dir is not None and args.snapshot is None,
    )

    if result.note:
        print(result.note.rstrip())
        print()
    print(f"word_count {result.word_count}")
    if result.stop_reason:
        print(f"stopped {result.stop_reason}")
    for check in result.checks:
        status = "pass" if check.passed else "fail"
        extra = f" ({check.detail})" if check.detail and not check.passed else ""
        print(f"check {check.check}: {status}{extra}")
    if result.funnel is not None:
        funnel = result.funnel.to_dict()
        print(
            "funnel "
            f"in {funnel['reviews_in']} "
            f"window {funnel['removed_by_window']} "
            f"emoji {funnel['removed_by_emoji_only']} "
            f"words {funnel['removed_by_word_count']} "
            f"language {funnel['removed_by_language']} "
            f"kept {funnel['reviews_kept']}"
        )
    print(f"passed {str(result.passed).lower()}")
    print(f"wrote {result.run_dir}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
