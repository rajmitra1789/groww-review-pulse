"""Streamlit preview and owner-triggered MCP publishing."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from pulse.config import SNAPSHOTS_DIR, WINDOW_WEEKS  # noqa: E402
from pulse.delivery.mcp_client import McpClient, McpError  # noqa: E402
from pulse.delivery.publish import publish, retry_draft  # noqa: E402
from pulse.filters import last_full_sunday  # noqa: E402
from pulse.models import PublishResult  # noqa: E402
from pulse.pipeline import (  # noqa: E402
    load_publish_result,
    record_publish_result,
    run_pulse,
)
from pulse.snapshot import SnapshotError  # noqa: E402

st.set_page_config(page_title="Groww Review Pulse", layout="wide")


def _snapshot_choices() -> list[Path]:
    if not SNAPSHOTS_DIR.exists():
        return []
    return sorted(
        [path for path in SNAPSHOTS_DIR.iterdir() if path.suffix.lower() in {".jsonl", ".csv"}],
        reverse=True,
    )


def _run_preview(snapshot: Path, week_ending: date, window_weeks: int):
    return run_pulse(snapshot, week_ending=week_ending, window_weeks=window_weeks)


def main() -> None:
    st.title("Groww Review Pulse")
    st.caption("Preview a one-page weekly note, then publish it when all checks pass.")

    snapshots = _snapshot_choices()
    names = [path.name for path in snapshots]
    with st.sidebar:
        st.header("Run")
        selected = st.selectbox("Snapshot", options=names, index=0 if names else None)
        uploaded = st.file_uploader("Or upload a snapshot", type=["jsonl", "csv"])
        week_ending = st.date_input("Week ending", value=last_full_sunday())
        window_weeks = st.slider("Window weeks", min_value=8, max_value=12, value=WINDOW_WEEKS)
        generate = st.button("Generate preview", type="primary")

    if generate:
        snapshot_path: Path | None = None
        if uploaded is not None:
            suffix = Path(uploaded.name).suffix or ".jsonl"
            with NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(uploaded.getvalue())
                snapshot_path = Path(handle.name)
        elif selected:
            snapshot_path = SNAPSHOTS_DIR / selected
        if snapshot_path is None:
            st.error("Pick or upload a snapshot.")
        else:
            try:
                with st.spinner("Generating preview…"):
                    st.session_state["pulse"] = _run_preview(
                        snapshot_path, week_ending, window_weeks
                    )
            except (SnapshotError, FileNotFoundError, OSError, RuntimeError) as exc:
                st.session_state.pop("pulse", None)
                st.error(str(exc))

    result = st.session_state.get("pulse")
    if result is None:
        st.info("Pick a snapshot and click Generate preview.")
        st.button("Publish", disabled=True, help="Generate a passing preview first.")
        return

    if result.stop_reason:
        st.error(result.stop_reason)

    note_col, meta_col = st.columns((3, 2))
    with note_col:
        st.subheader("Note")
        st.write(f"{result.word_count} words")
        if result.note:
            st.text(result.note)
        else:
            st.write("No note was assembled.")
    with meta_col:
        st.subheader("Checks")
        if result.checks:
            st.table(
                [
                    {
                        "check": item.check,
                        "result": "pass" if item.passed else "fail",
                        "detail": item.detail,
                    }
                    for item in result.checks
                ]
            )
        elif result.stop_reason:
            st.write("Checks did not run.")
        if result.funnel is not None:
            st.subheader("Funnel")
            st.table([result.funnel.to_dict()])
        if result.buckets is not None:
            st.caption(
                f"Noise {result.buckets.noise_count} · "
                f"generic praise {result.buckets.generic_praise_count} · "
                f"clusterable {result.buckets.clusterable_count}"
            )

    st.subheader("Themes")
    if result.themes:
        st.table(
            [
                {
                    "name": theme.name,
                    "size": theme.size,
                    "share": f"{theme.share_of_kept:.1%}",
                    "avg": f"{theme.average_rating:.1f}",
                    "complaint": f"{theme.complaint_share:.1%}",
                    "representatives": ", ".join(theme.representative_ids),
                }
                for theme in result.themes
            ]
        )
    else:
        st.write("No themes.")

    if result.zip_path is not None and result.zip_path.exists():
        st.download_button(
            "Download run zip",
            data=result.zip_path.read_bytes(),
            file_name=result.zip_path.name,
            mime="application/zip",
        )

    _delivery_controls(result)


def _delivery_controls(result) -> None:
    delivery = load_publish_result(result.run_dir)
    if delivery and delivery.doc_appended:
        st.success("The note was appended to the Google Doc.")
        st.link_button("Open Google Doc", delivery.doc_link)
        if delivery.draft_id:
            st.success("Gmail draft created.")
            return
        if delivery.error_code:
            st.error(f"{delivery.error_code}: {delivery.error_message}")
        if st.button("Retry draft", disabled=not result.passed):
            delivery = _run_delivery(result, draft_only=True)
            _show_delivery_result(delivery)
        return

    if delivery and delivery.error_code:
        st.error(f"{delivery.error_code}: {delivery.error_message}")
    if st.button(
        "Publish",
        type="primary",
        disabled=not result.passed,
        help=None if result.passed else "Every validation check must pass.",
    ):
        delivery = _run_delivery(result, draft_only=False)
        _show_delivery_result(delivery)


def _run_delivery(result, *, draft_only: bool) -> PublishResult:
    try:
        client = McpClient()
        delivery = (
            retry_draft(result, client) if draft_only else publish(result, client)
        )
    except McpError as exc:
        delivery = PublishResult(
            doc_link="",
            error_code=exc.code,
            error_message=exc.message,
            failed_step="configuration",
        )
    return record_publish_result(result, delivery)


def _show_delivery_result(delivery: PublishResult) -> None:
    if delivery.doc_appended and delivery.doc_link:
        st.success("The note was appended to the Google Doc.")
        st.link_button("Open Google Doc", delivery.doc_link)
    if delivery.draft_id:
        st.success("Gmail draft created.")
    elif delivery.error_code:
        st.error(f"{delivery.error_code}: {delivery.error_message}")


if __name__ == "__main__":
    main()
