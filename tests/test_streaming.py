import anyio
import httpx
from fastapi.testclient import TestClient

from backend.app.agent import Agent, SafetyDecision, SafetyVerdict
from backend.app.config import Settings
from backend.app.llm_client import (
    FoundryResponsesClient,
    LLMResult,
    MockLLMClient,
    ToolCall,
    _parse_sse_line,
    _sse_event_to_delta,
)
from backend.app.main import app, get_agent_llm, get_storage
from backend.app.storage import FileStorage


def _allow(_message):
    return SafetyVerdict(decision=SafetyDecision.ALLOW)


async def _acollect(agen):
    return [delta async for delta in agen]


# --- SSE parsing helpers (pure) -------------------------------------------


def test_parse_sse_line():
    assert _parse_sse_line('data: {"a": 1}') == {"a": 1}
    assert _parse_sse_line("data: [DONE]") is None
    assert _parse_sse_line(": comment") is None
    assert _parse_sse_line("") is None


def test_sse_event_to_delta_text():
    result = LLMResult()
    delta = _sse_event_to_delta({"type": "response.output_text.delta", "delta": "Hi"}, result)
    assert delta == "Hi"
    assert result.text == "Hi"


def test_sse_event_to_delta_function_call():
    result = LLMResult()
    event = {
        "type": "response.output_item.done",
        "item": {
            "type": "function_call",
            "call_id": "c1",
            "name": "get_profile",
            "arguments": "{}",
        },
    }
    assert _sse_event_to_delta(event, result) is None
    assert result.tool_calls[0].name == "get_profile"


# --- astream --------------------------------------------------------------


def test_base_astream_yields_text_and_records_result():
    async def run():
        result = LLMResult()
        client = MockLLMClient([LLMResult(text="hello")])
        chunks = [d async for d in client.astream([], result=result)]
        return chunks, result

    chunks, result = anyio.run(run)
    assert chunks == ["hello"]
    assert result.text == "hello"


def test_base_astream_records_tool_calls():
    async def run():
        result = LLMResult()
        scripted = LLMResult(tool_calls=[ToolCall("c", "add_goody", {})])
        chunks = [d async for d in MockLLMClient([scripted]).astream([], result=result)]
        return chunks, result

    chunks, result = anyio.run(run)
    assert chunks == []
    assert result.tool_calls[0].name == "add_goody"


def test_foundry_astream_parses_sse():
    sse = (
        'data: {"type": "response.output_text.delta", "delta": "Ho"}\n\n'
        'data: {"type": "response.output_text.delta", "delta": "la"}\n\n'
        'data: {"type": "response.output_item.done", "item": {"type": "function_call",'
        ' "call_id": "c1", "name": "get_profile", "arguments": "{}"}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request):
        return httpx.Response(200, text=sse)

    cfg = Settings(
        foundry_responses_url="https://x.openai.azure.com/responses", foundry_api_key="k"
    )
    client = FoundryResponsesClient(cfg, transport=httpx.MockTransport(handler))

    async def run():
        result = LLMResult()
        chunks = [
            d async for d in client.astream([{"role": "user", "content": "hi"}], result=result)
        ]
        return chunks, result

    chunks, result = anyio.run(run)
    assert chunks == ["Ho", "la"]
    assert result.text == "Hola"
    assert result.tool_calls[0].name == "get_profile"


# --- agent + endpoint + client --------------------------------------------


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
