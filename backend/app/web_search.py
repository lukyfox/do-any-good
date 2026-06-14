"""Web search via the Tavily API (backs the agent's web_search MCP tool).

Returns clean results (title/url/snippet). Disabled gracefully when no
TAVILY_API_KEY is configured. Swap the provider here if you prefer Brave/Bing.
"""
from __future__ import annotations

import httpx

from .config import get_settings

TAVILY_URL = "https://api.tavily.com/search"
REQUEST_TIMEOUT_SECONDS = 15


async def web_search(
    query: str, max_results: int = 5, *, transport: httpx.AsyncBaseTransport | None = None
) -> dict:
    """Search the web. Returns {"results": [...], "answer": ...} or {"error": ...}."""
    api_key = get_settings().tavily_api_key
    if not api_key:
        return {"error": "Web search is not configured (set TAVILY_API_KEY)."}
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "include_answer": True,
    }
    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS, transport=transport
        ) as client:
            response = await client.post(TAVILY_URL, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as err:
        return {"error": str(err)}
    results = [
        {"title": r.get("title"), "url": r.get("url"), "content": r.get("content")}
        for r in data.get("results", [])
    ]
    return {"results": results, "answer": data.get("answer")}
