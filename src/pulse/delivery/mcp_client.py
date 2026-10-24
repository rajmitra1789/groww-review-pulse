"""Small synchronous wrapper around the official streamable HTTP MCP client."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from pulse.config import get_setting

REQUIRED_TOOLS = frozenset({"google_docs_append_content", "gmail_create_draft"})


class McpError(RuntimeError):
    """An MCP transport, protocol, or tool error safe to show in the UI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class McpClient:
    """Call the delivery MCP server without holding Google credentials."""

    def __init__(self, url: str | None = None, auth_token: str | None = None) -> None:
        self.url = url or get_setting("MCP_SERVER_URL")
        self.auth_token = auth_token or get_setting("MCP_AUTH_TOKEN")
        if not self.url:
            raise McpError("MCP_CONFIG_MISSING", "MCP_SERVER_URL is not configured")
        if not self.auth_token:
            raise McpError("MCP_CONFIG_MISSING", "MCP_AUTH_TOKEN is not configured")

    def call_tool(self, name: str, args: dict[str, object]) -> dict[str, Any]:
        """Call one checked MCP tool and return its decoded JSON envelope."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise McpError(
                "MCP_CLIENT_ERROR",
                "MCP calls cannot start inside an active asyncio event loop",
            )
        try:
            return asyncio.run(self._call_tool(name, args))
        except McpError:
            raise
        except Exception as exc:
            raise McpError("MCP_CONNECTION_ERROR", str(exc)) from exc

    async def _call_tool(self, name: str, args: dict[str, object]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.auth_token}"}
        async with httpx2.AsyncClient(headers=headers) as http_client:
            async with streamable_http_client(
                self.url,
                http_client=http_client,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    available = {tool.name for tool in listed.tools}
                    missing = REQUIRED_TOOLS - available
                    if missing:
                        names = ", ".join(sorted(missing))
                        raise McpError(
                            "MCP_REQUIRED_TOOL_MISSING",
                            f"MCP server is missing required tool(s): {names}",
                        )
                    if name not in REQUIRED_TOOLS:
                        raise McpError(
                            "MCP_TOOL_NOT_ALLOWED",
                            f"MCP tool is not allowed: {name}",
                        )
                    response = await session.call_tool(name, arguments=args)
        return _parse_response(response)


def _parse_response(response: object) -> dict[str, Any]:
    # The SDK exposes the wire field ``structuredContent`` as the Python
    # attribute ``structured_content``. Keep the alias fallback for simple
    # test doubles and compatibility with older response wrappers.
    structured = getattr(response, "structured_content", None)
    if structured is None:
        structured = getattr(response, "structuredContent", None)
    payload: object = structured
    if not isinstance(payload, dict):
        texts = [
            item.text
            for item in (getattr(response, "content", None) or ())
            if isinstance(getattr(item, "text", None), str)
        ]
        if not texts:
            raise McpError("MCP_INVALID_RESPONSE", "MCP tool returned no JSON envelope")
        try:
            payload = json.loads("\n".join(texts))
        except json.JSONDecodeError as exc:
            raise McpError(
                "MCP_INVALID_RESPONSE", "MCP tool returned invalid JSON"
            ) from exc
    if not isinstance(payload, dict):
        raise McpError("MCP_INVALID_RESPONSE", "MCP tool returned a non-object envelope")
    if payload.get("ok") is False:
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "MCP_TOOL_ERROR")
            message = str(error.get("message") or "MCP tool failed")
        else:
            code, message = "MCP_TOOL_ERROR", "MCP tool failed"
        raise McpError(code, message)
    if payload.get("ok") is not True:
        raise McpError("MCP_INVALID_RESPONSE", "MCP tool response did not include ok: true")
    return payload
