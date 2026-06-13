import requests

from backend.app import llm_client
from backend.app.config import Settings


def test_mock_response_when_unconfigured(monkeypatch):
    monkeypatch.setattr(llm_client, "get_settings", lambda: Settings())
    out = llm_client.get_structured_response("hi", "decision")
    assert "response" in out
    assert out["response"]["text"].startswith("Mocked Foundry response")
    assert isinstance(out["response"]["suggestions"], list)


def test_azure_payload_shape():
    settings = Settings(
        foundry_responses_url="https://x.openai.azure.com/responses",
        foundry_api_key="k",
        foundry_model="gpt-4o",
    )
    payload = llm_client._build_payload("do good", "goodies_suggester", settings)
    assert payload["model"] == "gpt-4o"
    assert payload["input"][0]["role"] == "system"
    assert payload["input"][1]["content"] == "do good"


def test_non_azure_payload_shape():
    settings = Settings(
        foundry_responses_url="https://foundry.example.com/responses",
        foundry_api_key="k",
        foundry_project="proj",
    )
    payload = llm_client._build_payload("do good", "goodies_suggester", settings)
    assert payload["input"] == "do good"
    assert payload["requestClass"] == "goodies_suggester"
    assert payload["project"] == "proj"


def test_headers_azure_vs_bearer():
    azure = Settings(
        foundry_responses_url="https://x.openai.azure.com/responses",
        foundry_api_key="k",
    )
    other = Settings(
        foundry_responses_url="https://foundry.example.com/responses",
        foundry_api_key="k",
    )
    assert llm_client._headers(azure)["api-key"] == "k"
    assert llm_client._headers(other)["Authorization"] == "Bearer k"


def test_call_foundry_http_error(monkeypatch):
    settings = Settings(
        foundry_responses_url="https://foundry.example.com/responses",
        foundry_api_key="k",
    )
    monkeypatch.setattr(llm_client, "get_settings", lambda: settings)

    class _Resp:
        text = "bad"

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("boom")

        def json(self):
            return {"detail": "bad"}

    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: _Resp())
    out = llm_client.call_foundry_responses("q", "c")
    assert "error" in out
    assert out["body"] == {"detail": "bad"}
