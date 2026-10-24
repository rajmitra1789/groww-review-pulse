"""CLI preview of a weekly pulse, with explicit optional publishing."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse.config import WINDOW_WEEKS  # noqa: E402
from pulse.delivery.mcp_client import McpClient, McpError  # noqa: E402
from pulse.delivery.publish import publish, retry_draft  # noqa: E402
from pulse.filters import last_full_sunday  # noqa: E402
from pulse.pipeline import (  # noqa: E402
    load_publish_result,
    record_publish_result,
    run_pulse,
)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a weekly review pulse preview.")
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--run", type=Path, default=None, help="Reuse a run folder from phases 2-3.")
    parser.add_argument("--week-ending", type=_parse_date, default=None)
    parser.add_argument("--window-weeks", type=int, default=WINDOW_WEEKS)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Append to the Doc and create a Gmail draft after a passing preview.",
    )
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
    if args.publish:
        if not result.passed:
            print("publish refused: every validation check must pass")
            return 1
        try:
            existing = load_publish_result(result.run_dir)
            client = McpClient()
            if existing and existing.doc_appended:
                if existing.draft_id:
                    print("publish skipped: this week is already published")
                    return 0
                delivery = retry_draft(result, client)
            else:
                delivery = publish(result, client)
            delivery = record_publish_result(result, delivery)
        except McpError as exc:
            print(f"publish failed {exc.code}: {exc.message}")
            return 1
        if delivery.doc_appended:
            print(f"doc {delivery.doc_link}")
        if delivery.draft_id:
            print("draft created")
        if delivery.error_code:
            print(f"publish failed {delivery.error_code}: {delivery.error_message}")
            return 1
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
