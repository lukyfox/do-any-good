import anyio
import httpx

from backend.app import web_search as web_search_mod
from backend.app.config import Settings


def test_web_search_not_configured(monkeypatch):
    monkeypatch.setattr(web_search_mod, "get_settings", lambda: Settings())
    assert "error" in anyio.run(web_search_mod.web_search, "campaigns")


def test_web_search_returns_results(monkeypatch):
    monkeypatch.setattr(web_search_mod, "get_settings", lambda: Settings(tavily_api_key="k"))
    payload = {
        "answer": "Some campaigns.",
        "results": [{"title": "Donio campaign", "url": "https://donio.cz/x", "content": "Help X"}],
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    async def run():
        return await web_search_mod.web_search("campaigns", transport=httpx.MockTransport(handler))

    result = anyio.run(run)
    assert result["results"][0]["title"] == "Donio campaign"
    assert result["answer"] == "Some campaigns."


def test_web_search_http_error(monkeypatch):
    monkeypatch.setattr(web_search_mod, "get_settings", lambda: Settings(tavily_api_key="k"))

    def handler(request):
        return httpx.Response(500)

    async def run():
        return await web_search_mod.web_search("x", transport=httpx.MockTransport(handler))

    assert "error" in anyio.run(run)
