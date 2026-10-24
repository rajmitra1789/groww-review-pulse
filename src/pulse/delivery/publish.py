"""Deterministic Doc append and Gmail draft delivery through MCP."""

from __future__ import annotations

from typing import Any, Protocol

from pulse.config import get_setting
from pulse.delivery.mcp_client import McpError
from pulse.models import PublishResult, PulseResult

DOC_TOOL = "google_docs_append_content"
DRAFT_TOOL = "gmail_create_draft"


class ToolClient(Protocol):
    def call_tool(self, name: str, args: dict[str, object]) -> dict[str, Any]: ...


def publish(
    result: PulseResult,
    client: ToolClient,
    *,
    document_id: str | None = None,
    recipient: str | None = None,
) -> PublishResult:
    """Append the validated note, then create a draft. Never sends email."""
    if not result.passed:
        return _failure(
            "",
            "validation",
            "PULSE_VALIDATION_FAILED",
            "Publish requires a preview with every validation check passing",
        )
    doc_id, to = _delivery_settings(document_id, recipient)
    link = _doc_link(doc_id) if doc_id else ""
    if not doc_id or not to:
        return _failure(
            link,
            "configuration",
            "PULSE_CONFIG_MISSING",
            "PULSE_DOC_ID and PULSE_RECIPIENT must be configured",
        )

    try:
        appended = _call(
            client,
            DOC_TOOL,
            {
                "documentId": doc_id,
                "content": result.note,
                "ensureLeadingNewline": True,
            },
        )
    except McpError as exc:
        return _failure(link, "append", exc.code, exc.message)

    characters = appended.get("charactersAppended")
    if isinstance(characters, bool) or not isinstance(characters, int):
        return _failure(
            link,
            "append",
            "MCP_INVALID_RESPONSE",
            "Doc append response did not include charactersAppended",
        )

    try:
        drafted = _call(client, DRAFT_TOOL, _draft_args(result.note, doc_id, to))
    except McpError as exc:
        return PublishResult(
            doc_link=link,
            doc_appended=True,
            characters_appended=characters,
            failed_step="draft",
            error_code=exc.code,
            error_message=exc.message,
        )

    draft_id = drafted.get("draftId")
    if not isinstance(draft_id, str) or not draft_id:
        return PublishResult(
            doc_link=link,
            doc_appended=True,
            characters_appended=characters,
            failed_step="draft",
            error_code="MCP_INVALID_RESPONSE",
            error_message="Draft response did not include draftId",
        )
    return PublishResult(
        doc_link=link,
        doc_appended=True,
        characters_appended=characters,
        draft_id=draft_id,
    )


def retry_draft(
    result: PulseResult,
    client: ToolClient,
    *,
    document_id: str | None = None,
    recipient: str | None = None,
) -> PublishResult:
    """Retry only Gmail draft creation after a confirmed Doc append."""
    if not result.passed:
        return _failure(
            "",
            "validation",
            "PULSE_VALIDATION_FAILED",
            "Draft retry requires a preview with every validation check passing",
        )
    doc_id, to = _delivery_settings(document_id, recipient)
    link = _doc_link(doc_id) if doc_id else ""
    if not doc_id or not to:
        return _failure(
            link,
            "configuration",
            "PULSE_CONFIG_MISSING",
            "PULSE_DOC_ID and PULSE_RECIPIENT must be configured",
        )
    try:
        drafted = _call(client, DRAFT_TOOL, _draft_args(result.note, doc_id, to))
    except McpError as exc:
        return PublishResult(
            doc_link=link,
            doc_appended=True,
            failed_step="draft",
            error_code=exc.code,
            error_message=exc.message,
        )
    draft_id = drafted.get("draftId")
    if not isinstance(draft_id, str) or not draft_id:
        return PublishResult(
            doc_link=link,
            doc_appended=True,
            failed_step="draft",
            error_code="MCP_INVALID_RESPONSE",
            error_message="Draft response did not include draftId",
        )
    return PublishResult(doc_link=link, doc_appended=True, draft_id=draft_id)


def _call(
    client: ToolClient, name: str, args: dict[str, object]
) -> dict[str, Any]:
    try:
        envelope = client.call_tool(name, args)
    except McpError:
        raise
    except Exception as exc:
        raise McpError("MCP_CONNECTION_ERROR", str(exc)) from exc
    if not isinstance(envelope, dict):
        raise McpError("MCP_INVALID_RESPONSE", "MCP tool returned a non-object envelope")
    if envelope.get("ok") is False:
        error = envelope.get("error")
        if isinstance(error, dict):
            raise McpError(
                str(error.get("code") or "MCP_TOOL_ERROR"),
                str(error.get("message") or "MCP tool failed"),
            )
        raise McpError("MCP_TOOL_ERROR", "MCP tool failed")
    if envelope.get("ok") is not True:
        raise McpError("MCP_INVALID_RESPONSE", "MCP tool response did not include ok: true")
    return envelope


def _delivery_settings(
    document_id: str | None, recipient: str | None
) -> tuple[str, str]:
    return (
        document_id if document_id is not None else get_setting("PULSE_DOC_ID"),
        recipient if recipient is not None else get_setting("PULSE_RECIPIENT"),
    )


def _doc_link(document_id: str) -> str:
    return f"https://docs.google.com/document/d/{document_id}/edit"


def _draft_args(note: str, document_id: str, recipient: str) -> dict[str, object]:
    return {
        "to": [recipient],
        "subject": note.splitlines()[0],
        "body": f"{note.rstrip()}\n\n{_doc_link(document_id)}",
        "bodyType": "text",
    }


def _failure(link: str, step: str, code: str, message: str) -> PublishResult:
    return PublishResult(
        doc_link=link,
        failed_step=step,
        error_code=code,
        error_message=message,
    )
