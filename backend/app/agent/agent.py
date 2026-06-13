"""The Do Any Good agent: an MCP host that runs the LLM tool-calling loop.

The agent connects to the in-process MCP tools server, exposes its tools to the
LLM, and loops (model -> tool calls -> model) until the model returns a final
answer. Persistent state lives in storage; only the conversation turns are kept
in the returned history.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mcp.shared.memory import create_connected_server_and_client_session as connected

from ..llm_client import LLMClient
from ..mcp_server import build_mcp
from ..storage import FileStorage
from .prompts import SYSTEM_PROMPT

MAX_ITERATIONS = 6


@dataclass
class AgentResult:
    """Outcome of a single conversational turn."""

    reply: str
    history: list[dict[str, Any]] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)


def _tool_result_text(result) -> str:
    parts = [c.text for c in result.content if getattr(c, "text", None)]
    text = "\n".join(parts)
    if text:
        return text
    return "error" if result.isError else "null"


class Agent:
    """Runs one conversational turn, using MCP tools as needed."""

    def __init__(
        self,
        storage: FileStorage,
        llm: LLMClient,
        system_prompt: str = SYSTEM_PROMPT,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self.storage = storage
        self.llm = llm
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations

    async def _mcp_tools(self, session) -> list[dict[str, Any]]:
        listed = await session.list_tools()
        return [
            {"name": t.name, "description": t.description or "", "parameters": t.inputSchema}
            for t in listed.tools
        ]

    async def run(
        self, user_message: str, history: list[dict[str, Any]] | None = None
    ) -> AgentResult:
        history = history or []
        working: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            *history,
            {"role": "user", "content": user_message},
        ]
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

        new_history = [
            *history,
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reply},
        ]
        return AgentResult(reply=reply, history=new_history, tools_called=tools_called)
