"""The Do Any Good agent: an MCP host that runs the LLM tool-calling loop.

The agent first runs a safety gate (see safety.py). If the request is refused,
it returns a compassionate message with help resources without planning a deed.
Otherwise it connects to the in-process MCP tools server, exposes the tools to
the LLM, and loops (model -> tool calls -> model) until a final answer.
Persistent state lives in storage; only conversation turns are kept in history.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from mcp.shared.memory import create_connected_server_and_client_session as connected

from ..llm_client import LLMClient, LLMResult
from ..mcp_server import build_mcp
from ..storage import FileStorage, Goody
from .prompts import SYSTEM_PROMPT, profile_context
from .safety import LLMSafetyChecker, SafetyDecision, SafetyVerdict, refusal_message
from .suggestions import persist_one, persist_plan, suggest_daily, suggest_weekly

MAX_ITERATIONS = 6


@dataclass
class AgentResult:
    """Outcome of a single conversational turn."""

    reply: str
    history: list[dict[str, Any]] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    safety: SafetyDecision = SafetyDecision.ALLOW


def _tool_result_text(result) -> str:
    parts = [c.text for c in result.content if getattr(c, "text", None)]
    text = "\n".join(parts)
    if text:
        return text
    return "error" if result.isError else "null"


class Agent:
    """Runs one conversational turn, with a safety gate and MCP tools."""

    def __init__(
        self,
        storage: FileStorage,
        llm: LLMClient,
        system_prompt: str = SYSTEM_PROMPT,
        max_iterations: int = MAX_ITERATIONS,
        safety: Callable[[str], SafetyVerdict] | None = None,
    ) -> None:
        self.storage = storage
        self.llm = llm
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.safety = safety if safety is not None else LLMSafetyChecker(llm)

    def _turn(
        self,
        history: list[dict[str, Any]],
        user_message: str,
        reply: str,
        tools_called: list[str],
        decision: SafetyDecision,
    ) -> AgentResult:
        new_history = [
            *history,
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reply},
        ]
        return AgentResult(
            reply=reply, history=new_history, tools_called=tools_called, safety=decision
        )

    async def _mcp_tools(self, session) -> list[dict[str, Any]]:
        listed = await session.list_tools()
        return [
            {"name": t.name, "description": t.description or "", "parameters": t.inputSchema}
            for t in listed.tools
        ]

    def _build_working(
        self, history: list[dict[str, Any]], user_message: str, verdict: SafetyVerdict
    ) -> list[dict[str, Any]]:
        system_parts = [
            self.system_prompt,
            f"Today's date is {date.today().isoformat()}.",
            profile_context(self.storage.load_profile()),
        ]
        if verdict.decision == SafetyDecision.WARN and verdict.reason:
            system_parts.append(f"Safety note for this request: {verdict.reason}")
        return [
            {"role": "system", "content": "\n\n".join(system_parts)},
            *history,
            {"role": "user", "content": user_message},
        ]

    async def run(
        self, user_message: str, history: list[dict[str, Any]] | None = None
    ) -> AgentResult:
        history = history or []
        verdict = self.safety(user_message)
        if verdict.decision == SafetyDecision.REFUSE:
            return self._turn(
                history, user_message, refusal_message(verdict), [], verdict.decision
            )

        working = self._build_working(history, user_message, verdict)

        tools_called: list[str] = []
        reply = ""
        async with connected(build_mcp(self.storage)) as session:
            tools = await self._mcp_tools(session)
            for _ in range(self.max_iterations):
                result = self.llm.complete(working, tools=tools)
                if not result.tool_calls:
                    reply = result.text or ""
                    break
                for call in result.tool_calls:
                    tools_called.append(call.name)
                    output = await session.call_tool(call.name, call.arguments)
                    working.append(
                        {
                            "type": "function_call",
                            "call_id": call.call_id,
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        }
                    )
                    working.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.call_id,
                            "output": _tool_result_text(output),
                        }
                    )
            else:
                reply = "I couldn't complete that in time — could you rephrase?"

        return self._turn(history, user_message, reply, tools_called, verdict.decision)

    async def run_stream(
        self, user_message: str, history: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        """Stream the final reply text. A safety refusal is yielded whole; tool
        turns run silently; the final model turn streams its token deltas."""
        history = history or []
        verdict = self.safety(user_message)
        if verdict.decision == SafetyDecision.REFUSE:
            yield refusal_message(verdict)
            return

        working = self._build_working(history, user_message, verdict)
        async with connected(build_mcp(self.storage)) as session:
            tools = await self._mcp_tools(session)
            for _ in range(self.max_iterations):
                result = LLMResult()
                async for delta in self.llm.astream(working, tools=tools, result=result):
                    yield delta
                if not result.tool_calls:
                    return
                for call in result.tool_calls:
                    output = await session.call_tool(call.name, call.arguments)
                    working.append(
                        {
                            "type": "function_call",
                            "call_id": call.call_id,
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        }
                    )
                    working.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.call_id,
                            "output": _tool_result_text(output),
                        }
                    )
            yield "\n\n(I couldn't finish that in time - please try rephrasing.)"

    def suggest_today(self, on: date | None = None) -> Goody:
        """Generate and persist one planned Goody (defaults to tomorrow)."""
        on = on or date.today() + timedelta(days=1)
        suggestion = suggest_daily(self.llm, self.storage.load_profile())
        return persist_one(self.storage, suggestion, on)

    def suggest_week(self, start: date | None = None) -> list[Goody]:
        """Generate and persist a 7-day plan (defaults to starting tomorrow)."""
        start = start or date.today() + timedelta(days=1)
        suggestions = suggest_weekly(self.llm, self.storage.load_profile())
        return persist_plan(self.storage, suggestions, start)
