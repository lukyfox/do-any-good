"""Thin client for the Microsoft Foundry / Azure OpenAI Responses API.

M0 baseline: perform the HTTP call (or return a mock when unconfigured) and
return the parsed JSON response as-is. Native structured output and tool-calling
are added in M3 — there is intentionally no text-scraping here.
"""
from __future__ import annotations

from typing import Any

import requests

from .config import Settings, get_settings

REQUEST_TIMEOUT_SECONDS = 15


def _normalize_url(url: str) -> str:
    url = url.rstrip("/")
    if "openai.azure.com" in url and not url.endswith("/responses"):
        return url + "/responses"
    return url


def _headers(settings: Settings) -> dict[str, str]:
    if settings.is_azure_openai:
        return {"api-key": settings.foundry_api_key or "", "Content-Type": "application/json"}
    return {
        "Authorization": f"Bearer {settings.foundry_api_key}",
        "Content-Type": "application/json",
    }


def _mock_response(question: str, request_class: str) -> dict[str, Any]:
    return {
        "text": f"Mocked Foundry response for '{question}' (class={request_class}).",
        "suggestions": [
            {"title": "Help a neighbor", "category": "others"},
            {"title": "Take a mindful walk", "category": "self"},
        ],
    }


def _build_payload(question: str, request_class: str, settings: Settings) -> dict[str, Any]:
    if settings.is_azure_openai:
        system_prompt = (
            f"Request class: {request_class}. Suggest helpful, safe good deeds for the user."
        )
        payload: dict[str, Any] = {
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        }
        if settings.foundry_model:
            payload["model"] = settings.foundry_model
        return payload

    payload = {"input": question, "requestClass": request_class}
    if settings.foundry_model:
        payload["model"] = settings.foundry_model
    if settings.foundry_project:
        payload["project"] = settings.foundry_project
    return payload


def call_foundry_responses(question: str, request_class: str) -> dict[str, Any]:
    """Call the Foundry/Azure Responses API, or return a mock when not configured."""
    settings = get_settings()
    if not settings.foundry_configured:
        return _mock_response(question, request_class)
    if settings.is_azure_openai and not settings.foundry_model:
        return {"error": "FOUNDRY_MODEL is required for Azure OpenAI Responses endpoints."}

    url = _normalize_url(settings.foundry_responses_url or "")
    try:
        response = requests.post(
            url,
            json=_build_payload(question, request_class, settings),
            headers=_headers(settings),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as err:
        try:
            body: Any = response.json()
        except Exception:
            body = response.text
        return {"error": str(err), "body": body, "url": url}
    except requests.exceptions.RequestException as err:
        return {"error": str(err), "url": url}


def get_structured_response(question: str, request_class: str) -> dict[str, Any]:
    """Return the raw Foundry/mock response in a stable envelope.

    M3 replaces this with structured-output + tool-calling parsing.
    """
    return {"response": call_foundry_responses(question, request_class)}
