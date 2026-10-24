from __future__ import annotations

from pathlib import Path


def test_src_has_no_direct_google_sdk_or_send_tool() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    forbidden = ("googleapiclient", "google.oauth2", "gmail_" + "send_email")
    matches: list[str] = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for value in forbidden:
            if value in text:
                matches.append(f"{path.relative_to(src)}: {value}")
    assert matches == []
