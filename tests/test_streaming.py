import anyio
from fastapi.testclient import TestClient

from backend.app import llm_client
from backend.app.agent import Agent, SafetyDecision, SafetyVerdict
from backend.app.config import Settings
from backend.app.llm_client import FoundryResponsesClient, LLMResult, MockLLMClient, ToolCall
from backend.app.main import app, get_agent_llm, get_storage
from backend.app.storage import FileStorage


def _allow(_message):
    return SafetyVerdict(decision=SafetyDecision.ALLOW)


def _drain(gen):
    chunks = []
    try:
        while True:
            chunks.append(next(gen))
    except StopIteration as stop:
        return chunks, stop.value


async def _acollect(agen):
    return [delta async for delta in agen]


def test_base_stream_is_nonstreaming_fallback():
    chunks, result = _drain(MockLLMClient([LLMResult(text="hello")]).stream([]))
    assert chunks == ["hello"]
    assert result.text == "hello"


def test_base_stream_surfaces_tool_calls():
    scripted = LLMResult(tool_calls=[ToolCall("c1", "add_goody", {})])
    chunks, result = _drain(MockLLMClient([scripted]).stream([]))
    assert chunks == []
    assert result.tool_calls[0].name == "add_goody"


def test_foundry_stream_parses_text_and_tools(monkeypatch):
    lines = [
        'data: {"type": "response.output_text.delta", "delta": "Hel"}',
        'data: {"type": "response.output_text.delta", "delta": "lo"}',
        'data: {"type": "response.output_item.done", "item": {"type": "function_call",'
        ' "call_id": "c1", "name": "get_profile", "arguments": "{}"}}',
        "data: [DONE]",
    ]

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self, decode_unicode=False):
            yield from lines

    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: _Resp())
    cfg = Settings(
        foundry_responses_url="https://x.openai.azure.com/responses", foundry_api_key="k"
    )
    chunks, result = _drain(
        FoundryResponsesClient(cfg).stream([{"role": "user", "content": "hi"}])
    )
    assert chunks == ["Hel", "lo"]
    assert result.text == "Hello"
    assert result.tool_calls[0].name == "get_profile"


def test_agent_run_stream_yields_text(tmp_path):
    agent = Agent(FileStorage(tmp_path), MockLLMClient([LLMResult(text="Ahoj")]), safety=_allow)
    chunks = anyio.run(_acollect, agent.run_stream("hi"))
    assert "".join(chunks) == "Ahoj"


def test_agent_run_stream_executes_tool(tmp_path):
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
            LLMResult(text="Done!"),
        ]
    )
    agent = Agent(storage, llm, safety=_allow)
    chunks = anyio.run(_acollect, agent.run_stream("plan"))
    assert "".join(chunks) == "Done!"
    assert [g.title for g in storage.list_goodies()] == ["Call gran"]


def test_agent_run_stream_refusal(tmp_path):
    def refuse(_message):
        return SafetyVerdict(decision=SafetyDecision.REFUSE, reason="Please get help.")

    agent = Agent(FileStorage(tmp_path), MockLLMClient([]), safety=refuse)
    chunks = anyio.run(_acollect, agent.run_stream("bad"))
    assert "Please get help." in "".join(chunks)


def test_chat_stream_endpoint(tmp_path):
    app.dependency_overrides[get_storage] = lambda: FileStorage(tmp_path)
    app.dependency_overrides[get_agent_llm] = lambda: MockLLMClient(
        [
            LLMResult(parsed={"decision": "allow", "reason": "", "resources": []}),
            LLMResult(text="Ahoj!"),
        ]
    )
    try:
        with TestClient(app) as client:
            with client.stream("POST", "/chat/stream", json={"message": "Hi", "history": []}) as r:
                body = "".join(r.iter_text())
        assert body == "Ahoj!"
    finally:
        app.dependency_overrides.clear()


def test_client_stream_chat(monkeypatch):
    from client import gradio_app

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=None):
            yield b"Ah"
            yield b"oj"

    monkeypatch.setattr(gradio_app.requests, "post", lambda *a, **k: _Resp())
    assert "".join(gradio_app.stream_chat("hi", [])) == "Ahoj"
