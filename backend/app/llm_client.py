"""LLM client for the Microsoft Foundry / Azure OpenAI Responses API.

Exposes a thin, normalized interface (LLMClient.complete -> LLMResult) carrying
assistant text, tool calls, and parsed structured output. The real client
targets the Responses API (/responses) with native function tools and
json_schema structured output; MockLLMClient is used offline and in tests.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import requests

from .config import Settings, get_settings

REQUEST_TIMEOUT_SECONDS = 30


@dataclass
class ToolCall:
    """A function/tool call requested by the model."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResult:
    """Normalized result of an LLM completion."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    parsed: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


def _headers(settings: Settings) -> dict[str, str]:
    if settings.is_azure_openai:
        return {"api-key": settings.foundry_api_key or "", "Content-Type": "application/json"}
    return {
        "Authorization": f"Bearer {settings.foundry_api_key}",
        "Content-Type": "application/json",
    }


def _to_responses_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Map a tool to the Responses API shape.

    Built-in tools (e.g. {"type": "web_search"}) pass through unchanged; a
    {name, description, parameters} function tool is wrapped as a function tool.
    """
    if "name" not in tool:
        return tool
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
    }


def build_responses_payload(
    messages: list[dict[str, Any]],
    *,
    model: str | None,
    tools: list[dict[str, Any]] | None = None,
    response_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Responses API request body."""
    payload: dict[str, Any] = {"input": messages}
    if model:
        payload["model"] = model
    if tools:
        payload["tools"] = [_to_responses_tool(t) for t in tools]
    if response_schema:
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": response_schema.get("name", "result"),
                "schema": response_schema["schema"],
                "strict": response_schema.get("strict", True),
            }
        }
    return payload


def _try_parse_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def parse_responses(payload: dict[str, Any]) -> LLMResult:
    """Parse a Responses API response body into a normalized LLMResult."""
    result = LLMResult(raw=payload)
    texts: list[str] = []
    for item in payload.get("output", []):
        item_type = item.get("type")
        if item_type == "function_call":
            raw_args = item.get("arguments")
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
            else:
                arguments = raw_args or {}
            result.tool_calls.append(
                ToolCall(
                    call_id=item.get("call_id") or item.get("id", ""),
                    name=item.get("name", ""),
                    arguments=arguments,
                )
            )
        elif item_type == "message":
            for part in item.get("content", []):
                if part.get("type") in ("output_text", "text"):
                    texts.append(part.get("text", ""))
    if not texts and isinstance(payload.get("output_text"), str):
        texts.append(payload["output_text"])
    result.text = "\n".join(t for t in texts if t) or None
    if result.text:
        result.parsed = _try_parse_json(result.text)
    return result


def _parse_sse_line(raw: str) -> dict[str, Any] | None:
    """Parse one SSE `data:` line into a JSON object (None for blanks/[DONE])."""
    if not raw or not raw.startswith("data:"):
        return None
    payload = raw[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _sse_event_to_delta(data: dict[str, Any], result: LLMResult) -> str | None:
    """Apply one Responses API stream event to `result`; return any text delta."""
    kind = data.get("type")
    if kind == "response.output_text.delta":
        delta = data.get("delta", "")
        if delta:
            result.text = (result.text or "") + delta
            return delta
    elif kind == "response.output_item.done":
        item = data.get("item", {})
        if item.get("type") == "function_call":
            result.tool_calls.append(_function_call_from_item(item))
    return None


def _function_call_from_item(item: dict[str, Any]) -> ToolCall:
    try:
        arguments = json.loads(item.get("arguments") or "{}")
    except json.JSONDecodeError:
        arguments = {}
    return ToolCall(
        call_id=item.get("call_id") or item.get("id", ""),
        name=item.get("name", ""),
        arguments=arguments,
    )


class LLMClient:
    """Interface for completion backends."""

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        raise NotImplementedError

    async def astream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        result: LLMResult | None = None,
    ) -> AsyncIterator[str]:
        """Yield reply text deltas, recording the outcome into `result`.

        Default: a non-streaming fallback that emits the whole reply as one chunk.
        """
        outcome = self.complete(messages, tools=tools)
        if result is not None:
            result.text = outcome.text
            result.tool_calls = outcome.tool_calls
            result.parsed = outcome.parsed
        if outcome.text:
            yield outcome.text


class MockLLMClient(LLMClient):
    """Deterministic client for offline/dev and tests.

    Returns queued results in order if provided; otherwise echoes the last
    user message as text."""

    def __init__(self, scripted: list[LLMResult] | None = None) -> None:
        self._scripted = list(scripted or [])

    def complete(self, messages, *, tools=None, response_schema=None) -> LLMResult:
        if self._scripted:
            return self._scripted.pop(0)
        last_user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        return LLMResult(text=f"[mock] {last_user}")


class FoundryResponsesClient(LLMClient):
    """Calls the Azure/Foundry Responses API."""

    def __init__(
        self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    def complete(self, messages, *, tools=None, response_schema=None) -> LLMResult:
        s = self._settings
        payload = build_responses_payload(
            messages, model=s.foundry_model, tools=tools, response_schema=response_schema
        )
        url = (s.foundry_responses_url or "").rstrip("/")
        response = requests.post(
            url, json=payload, headers=_headers(s), timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return parse_responses(response.json())

    async def astream(self, messages, *, tools=None, result=None) -> AsyncIterator[str]:
        result = result if result is not None else LLMResult()
        s = self._settings
        payload = build_responses_payload(messages, model=s.foundry_model, tools=tools)
        payload["stream"] = True
        url = (s.foundry_responses_url or "").rstrip("/")
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            async with client.stream("POST", url, json=payload, headers=_headers(s)) as response:
                response.raise_for_status()
                async for raw in response.aiter_lines():
                    data = _parse_sse_line(raw)
                    if data is None:
                        continue
                    delta = _sse_event_to_delta(data, result)
                    if delta:
                        yield delta


def get_llm_client() -> LLMClient:
    """Return a real client when Foundry is configured, else a mock."""
    settings = get_settings()
    if settings.foundry_configured:
        return FoundryResponsesClient(settings)
    return MockLLMClient()
