from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import pulse.delivery.mcp_client as module
from pulse.delivery.mcp_client import McpClient, McpError


class AsyncContext:
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeHttpClient(AsyncContext):
    def __init__(self, *, headers: dict[str, str]) -> None:
        super().__init__(self)
        self.headers = headers


class FakeSession(AsyncContext):
    tool_names = {"google_docs_append_content", "gmail_create_draft"}

    def __init__(self, read: object, write: object) -> None:
        super().__init__(self)
        self.read = read
        self.write = write

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(
            tools=[SimpleNamespace(name=name) for name in self.tool_names]
        )

    async def call_tool(
        self, name: str, arguments: dict[str, object]
    ) -> SimpleNamespace:
        payload = {"ok": True, "draftId": "draft"} if "draft" in name else {
            "ok": True,
            "charactersAppended": 10,
        }
        return SimpleNamespace(
            structuredContent=None,
            content=[SimpleNamespace(text=json.dumps(payload))],
        )


def test_exact_url_and_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def http_factory(*, headers: dict[str, str]) -> FakeHttpClient:
        client = FakeHttpClient(headers=headers)
        seen["headers"] = client.headers
        return client

    def stream_factory(
        url: str, *, http_client: FakeHttpClient
    ) -> AsyncContext:
        seen["url"] = url
        seen["http_client"] = http_client
        return AsyncContext(("read", "write"))

    monkeypatch.setattr(module.httpx2, "AsyncClient", http_factory)
    monkeypatch.setattr(module, "streamable_http_client", stream_factory)
    monkeypatch.setattr(module, "ClientSession", FakeSession)

    url = "https://mcp.example.test"
    client = McpClient(url=url, auth_token="test-token")
    result = client.call_tool(
        "google_docs_append_content",
        {"documentId": "doc", "content": "note", "ensureLeadingNewline": True},
    )

    assert result["ok"] is True
    assert seen["url"] == url
    assert seen["headers"] == {"Authorization": "Bearer test-token"}


def test_missing_required_tool_stops_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingToolSession(FakeSession):
        tool_names = {"google_docs_append_content"}

    monkeypatch.setattr(module.httpx2, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(
        module,
        "streamable_http_client",
        lambda url, *, http_client: AsyncContext(("read", "write")),
    )
    monkeypatch.setattr(module, "ClientSession", MissingToolSession)

    with pytest.raises(McpError, match="gmail_create_draft") as caught:
        McpClient(url="https://mcp.example.test", auth_token="token").call_tool(
            "google_docs_append_content", {}
        )
    assert caught.value.code == "MCP_REQUIRED_TOOL_MISSING"
