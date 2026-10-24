from __future__ import annotations

from datetime import date
from pathlib import Path

from pulse.delivery.publish import publish, retry_draft
from pulse.models import Failure, PublishResult, PulseResult
from pulse.pipeline import load_publish_result, record_publish_result


class FakeMcpClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, name: str, args: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, args))
        return self.responses.pop(0)


def _pulse(tmp_path: Path, *, failed: bool = False) -> PulseResult:
    return PulseResult(
        week_ending=date(2026, 10, 18),
        window_weeks=12,
        window_start=date(2026, 7, 27),
        note="Groww Review Pulse - week of 12 Oct 2026\n\nValidated note.",
        word_count=10,
        failures=(Failure("Length", "too long"),) if failed else (),
        checks=(),
        funnel=None,
        buckets=None,
        themes=(),
        top_themes=(),
        compose=None,
        reviews=(),
        run_dir=tmp_path,
        zip_path=None,
        k=0,
        silhouette=None,
    )


def test_publish_appends_then_creates_draft(tmp_path: Path) -> None:
    client = FakeMcpClient(
        [
            {"ok": True, "charactersAppended": 58},
            {"ok": True, "draftId": "draft-1"},
        ]
    )
    result = publish(
        _pulse(tmp_path),
        client,
        document_id="doc-123",
        recipient="owner@example.com",
    )

    assert result.passed
    assert [name for name, _ in client.calls] == [
        "google_docs_append_content",
        "gmail_create_draft",
    ]
    append_args = client.calls[0][1]
    assert append_args["documentId"] == "doc-123"
    assert append_args["ensureLeadingNewline"] is True
    assert append_args["content"] == _pulse(tmp_path).note
    draft_args = client.calls[1][1]
    assert draft_args["to"] == ["owner@example.com"]
    assert draft_args["bodyType"] == "text"
    assert _pulse(tmp_path).note in str(draft_args["body"])
    assert "https://docs.google.com/document/d/doc-123/edit" in str(draft_args["body"])
    assert draft_args["subject"] == _pulse(tmp_path).note.splitlines()[0]
    assert all(name != "gmail_" + "send_email" for name, _ in client.calls)


def test_failed_append_stops_before_draft(tmp_path: Path) -> None:
    client = FakeMcpClient(
        [{"ok": False, "error": {"code": "DOC_NOT_FOUND", "message": "missing"}}]
    )
    result = publish(
        _pulse(tmp_path), client, document_id="doc", recipient="owner@example.com"
    )
    assert not result.doc_appended
    assert result.error_code == "DOC_NOT_FOUND"
    assert [name for name, _ in client.calls] == ["google_docs_append_content"]


def test_failed_draft_preserves_append_result(tmp_path: Path) -> None:
    client = FakeMcpClient(
        [
            {"ok": True, "charactersAppended": 58},
            {
                "ok": False,
                "error": {"code": "GMAIL_DRAFT_CREATE_FAILED", "message": "failed"},
            },
        ]
    )
    result = publish(
        _pulse(tmp_path), client, document_id="doc", recipient="owner@example.com"
    )
    assert result.doc_appended
    assert result.characters_appended == 58
    assert result.draft_id is None
    assert result.failed_step == "draft"


def test_retry_draft_calls_only_draft(tmp_path: Path) -> None:
    client = FakeMcpClient([{"ok": True, "draftId": "draft-2"}])
    result = retry_draft(
        _pulse(tmp_path), client, document_id="doc", recipient="owner@example.com"
    )
    assert result.draft_id == "draft-2"
    assert [name for name, _ in client.calls] == ["gmail_create_draft"]


def test_publish_refuses_failed_validation(tmp_path: Path) -> None:
    client = FakeMcpClient([])
    result = publish(
        _pulse(tmp_path, failed=True),
        client,
        document_id="doc",
        recipient="owner@example.com",
    )
    assert result.error_code == "PULSE_VALIDATION_FAILED"
    assert client.calls == []


def test_retry_artifact_keeps_confirmed_append(tmp_path: Path) -> None:
    pulse = _pulse(tmp_path)
    record_publish_result(
        pulse,
        PublishResult(
            doc_link="https://docs.google.com/document/d/doc/edit",
            doc_appended=True,
            characters_appended=58,
            failed_step="draft",
            error_code="GMAIL_DRAFT_CREATE_FAILED",
            error_message="failed",
        ),
    )
    record_publish_result(
        pulse,
        PublishResult(
            doc_link="https://docs.google.com/document/d/doc/edit",
            doc_appended=True,
            draft_id="draft-2",
        ),
    )
    saved = load_publish_result(tmp_path)
    assert saved is not None
    assert saved.doc_appended
    assert saved.characters_appended == 58
    assert saved.draft_id == "draft-2"
