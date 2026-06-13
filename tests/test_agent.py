import anyio
from fastapi.testclient import TestClient

from backend.app.agent import Agent
from backend.app.llm_client import LLMClient, LLMResult, MockLLMClient, ToolCall
from backend.app.main import app, get_agent_llm, get_storage
from backend.app.storage import FileStorage

MCP_TOOL_NAMES = {
    "get_profile",
    "upsert_profile",
    "add_goody",
    "list_goodies",
    "set_goody_status",
    "append_journal",
}


class _RecordingLLM(LLMClient):
    """Captures the tools handed to the model, then replies with plain text."""

    def __init__(self):
        self.tools_seen = None

    def complete(self, messages, *, tools=None, response_schema=None):
        self.tools_seen = tools
        return LLMResult(text="ok")


class _AlwaysToolLLM(LLMClient):
    """Always asks for another tool call — used to test the iteration cap."""

    def __init__(self):
        self.calls = 0

    def complete(self, messages, *, tools=None, response_schema=None):
        self.calls += 1
        return LLMResult(tool_calls=[ToolCall(f"c{self.calls}", "list_goodies", {})])


def test_agent_plain_reply(tmp_path):
    agent = Agent(FileStorage(tmp_path), MockLLMClient([LLMResult(text="Ahoj!")]))
    res = anyio.run(agent.run, "Hi")
    assert res.reply == "Ahoj!"
    assert res.tools_called == []
    assert res.history[-1] == {"role": "assistant", "content": "Ahoj!"}


def test_agent_executes_tool_then_replies(tmp_path):
    storage = FileStorage(tmp_path)
    llm = MockLLMClient(
        [
            LLMResult(
                tool_calls=[
                    ToolCall(
                        "c1",
                        "add_goody",
                        {"date": "2026-06-14", "title": "Call gran", "category": "others"},
                    )
                ]
            ),
            LLMResult(text="Added it!"),
        ]
    )
    res = anyio.run(Agent(storage, llm).run, "plan a goody")
    assert res.reply == "Added it!"
    assert res.tools_called == ["add_goody"]
    assert [g.title for g in storage.list_goodies()] == ["Call gran"]  # tool hit storage


def test_agent_exposes_mcp_tools(tmp_path):
    llm = _RecordingLLM()
    anyio.run(Agent(FileStorage(tmp_path), llm).run, "hi")
    names = {t["name"] for t in llm.tools_seen}
    assert MCP_TOOL_NAMES <= names
    assert all("parameters" in t for t in llm.tools_seen)


def test_agent_stops_at_max_iterations(tmp_path):
    agent = Agent(FileStorage(tmp_path), _AlwaysToolLLM(), max_iterations=3)
    res = anyio.run(agent.run, "loop forever")
    assert len(res.tools_called) == 3
    assert res.reply


def test_chat_endpoint(tmp_path):
    app.dependency_overrides[get_storage] = lambda: FileStorage(tmp_path)
    app.dependency_overrides[get_agent_llm] = lambda: MockLLMClient([LLMResult(text="Ahoj!")])
    try:
        r = TestClient(app).post("/chat", json={"message": "Hi"})
        assert r.status_code == 200
        body = r.json()
        assert body["reply"] == "Ahoj!"
        assert body["history"][-1]["content"] == "Ahoj!"
    finally:
        app.dependency_overrides.clear()
