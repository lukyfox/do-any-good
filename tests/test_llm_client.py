from backend.app import llm_client
from backend.app.config import Settings
from backend.app.llm_client import (
    FoundryResponsesClient,
    LLMResult,
    MockLLMClient,
    ToolCall,
    build_responses_payload,
    parse_responses,
)

MSG_RESPONSE = {
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hello there"}],
        }
    ]
}
FUNC_RESPONSE = {
    "output": [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "get_profile",
            "arguments": '{"x": 1}',
        }
    ]
}
JSON_RESPONSE = {
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": '{"suggestions": ["a"]}'}],
        }
    ]
}
OT_RESPONSE = {"output": [], "output_text": "Quick text"}


def test_build_payload_minimal():
    p = build_responses_payload([{"role": "user", "content": "hi"}], model="m")
    assert p["input"] == [{"role": "user", "content": "hi"}]
    assert p["model"] == "m"
    assert "tools" not in p and "text" not in p


def test_build_payload_passes_builtin_tool_through():
    tools = [{"name": "t", "parameters": {"type": "object"}}, {"type": "web_search"}]
    payload = build_responses_payload([{"role": "user", "content": "hi"}], model=None, tools=tools)
    assert {"type": "web_search"} in payload["tools"]
    assert any(t.get("type") == "function" and t.get("name") == "t" for t in payload["tools"])


def test_build_payload_tools_and_schema():
    tools = [{"name": "t", "description": "d", "parameters": {"type": "object"}}]
    schema = {"name": "out", "schema": {"type": "object"}}
    p = build_responses_payload(
        [{"role": "user", "content": "hi"}], model=None, tools=tools, response_schema=schema
    )
    assert "model" not in p
    assert p["tools"][0] == {
        "type": "function",
        "name": "t",
        "description": "d",
        "parameters": {"type": "object"},
    }
    assert p["text"]["format"]["type"] == "json_schema"
    assert p["text"]["format"]["schema"] == {"type": "object"}
    assert p["text"]["format"]["strict"] is True


def test_parse_message_text():
    r = parse_responses(MSG_RESPONSE)
    assert r.text == "Hello there"
    assert r.parsed is None
    assert r.tool_calls == []


def test_parse_function_call():
    r = parse_responses(FUNC_RESPONSE)
    assert r.text is None
    assert len(r.tool_calls) == 1
    tc = r.tool_calls[0]
    assert (tc.call_id, tc.name, tc.arguments) == ("call_1", "get_profile", {"x": 1})


def test_parse_structured_json():
    assert parse_responses(JSON_RESPONSE).parsed == {"suggestions": ["a"]}


def test_parse_output_text_convenience():
    assert parse_responses(OT_RESPONSE).text == "Quick text"


def test_mock_default_echo():
    r = MockLLMClient().complete([{"role": "user", "content": "hello"}])
    assert "hello" in r.text


def test_mock_scripted_order():
    client = MockLLMClient(
        [LLMResult(text="first"), LLMResult(tool_calls=[ToolCall("c", "n", {})])]
    )
    assert client.complete([]).text == "first"
    assert client.complete([]).tool_calls[0].name == "n"


def test_get_llm_client_selects_impl(monkeypatch):
    monkeypatch.setattr(llm_client, "get_settings", lambda: Settings())
    assert isinstance(llm_client.get_llm_client(), MockLLMClient)
    cfg = Settings(
        foundry_responses_url="https://x.openai.azure.com/responses", foundry_api_key="k"
    )
    monkeypatch.setattr(llm_client, "get_settings", lambda: cfg)
    assert isinstance(llm_client.get_llm_client(), FoundryResponsesClient)


def test_headers_azure_vs_bearer():
    azure = Settings(
        foundry_responses_url="https://x.openai.azure.com/responses", foundry_api_key="k"
    )
    other = Settings(
        foundry_responses_url="https://foundry.example.com/responses", foundry_api_key="k"
    )
    assert llm_client._headers(azure)["api-key"] == "k"
    assert llm_client._headers(other)["Authorization"] == "Bearer k"


def test_foundry_complete_posts_and_parses(monkeypatch):
    cfg = Settings(
        foundry_responses_url="https://x.openai.azure.com/responses/",
        foundry_api_key="k",
        foundry_model="dep",
    )
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return MSG_RESPONSE

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return _Resp()

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    result = FoundryResponsesClient(cfg).complete(
        [{"role": "user", "content": "hi"}], tools=[{"name": "t"}]
    )
    assert result.text == "Hello there"
    assert captured["url"] == "https://x.openai.azure.com/responses"  # trailing slash trimmed
    assert captured["json"]["model"] == "dep"
    assert captured["headers"]["api-key"] == "k"
    assert captured["json"]["tools"][0]["name"] == "t"
