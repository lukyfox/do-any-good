import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from typing import Any, Dict, Optional
import json
import re

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

FOUNDARY_URL = os.getenv("FOUNDRY_RESPONSES_URL")
API_KEY = os.getenv("FOUNDRY_API_KEY")
FOUNDRY_PROJECT = os.getenv("FOUNDRY_PROJECT")
FOUNDRY_MODEL = os.getenv("FOUNDRY_MODEL")


def _normalize_foundry_url(url: str) -> str:
    if url.endswith("/responses") or url.endswith("/responses/"):
        return url.rstrip("/")
    if "openai.azure.com" in url and not url.rstrip("/").endswith("/responses"):
        return url.rstrip("/") + "/responses"
    return url.rstrip("/")


def _build_headers(url: str) -> Dict[str, str]:
    if "openai.azure.com" in url:
        return {"api-key": API_KEY, "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def _mock_response(question: str, request_class: str) -> Dict[str, Any]:
    return {
        "text": f"Mocked Foundry response for '{question}' (class={request_class}).",
        "suggestions": [
            {"title": "Help a neighbor", "age_suitability": "all", "location_needed": False},
            {"title": "Plant local trees", "age_suitability": "18+", "location_needed": True},
        ],
    }


def _extract_response(payload: Dict[str, Any]) -> Any:
    # Handle native Foundry shape
    if "response" in payload:
        return payload["response"]

    # Azure/OpenAI Responses shape: { 'id', 'type', 'status', 'content': [ {type:'output_text', 'text': '...'} ] }
    if isinstance(payload, dict) and "content" in payload and isinstance(payload["content"], list):
        texts = []
        for item in payload["content"]:
            if isinstance(item, dict) and item.get("type") == "output_text":
                texts.append(item.get("text", ""))
        full = "\n".join(texts)
        # Try to parse JSON embedded in the text
        parsed = _try_extract_json(full)
        return {"raw": full, "parsed": parsed}

    # Older Foundry style 'output'
    if "output" in payload:
        output = payload["output"]
        if isinstance(output, list):
            return "\n".join(str(item) for item in output)
        return output

    return payload


def _try_extract_json(text: str) -> Optional[Any]:
    """Attempt to find and parse JSON in a text blob.

    Returns parsed JSON or None on failure.
    """
    text = text.strip()
    # Direct parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # Find first JSON object or array in text
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not m:
        return None
    candidate = m.group(1)
    # Try to balance braces if truncated
    try:
        return json.loads(candidate)
    except Exception:
        # Attempt to trim trailing commas/newlines and retry
        candidate = candidate.strip()
        # Heuristic: find last closing brace
        last = candidate.rfind('}')
        if last != -1:
            candidate = candidate[: last + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return None


def call_foundry_responses(question: str, request_class: str) -> Any:
    """Call Microsoft Foundry Responses API, or return a mock response when not configured."""
    if not FOUNDARY_URL or not API_KEY:
        return _mock_response(question, request_class)

    if "openai.azure.com" in FOUNDARY_URL:
        if not FOUNDRY_MODEL:
            return {
                "error": "FOUNDRY_MODEL is required for Azure OpenAI Responses endpoints.",
                "url": FOUNDARY_URL,
            }
        system_prompt = f"Request class: {request_class}. Create helpful good deed suggestions for a user based on personality, location and age."
        payload = {
            "model": FOUNDRY_MODEL,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        }
    else:
        payload = {
            "input": question,
            "requestClass": request_class,
            **({"model": FOUNDRY_MODEL} if FOUNDRY_MODEL else {}),
        }
        if FOUNDRY_PROJECT:
            payload["project"] = FOUNDRY_PROJECT

    foundry_url = _normalize_foundry_url(FOUNDARY_URL)
    headers = _build_headers(foundry_url)
    try:
        response = requests.post(foundry_url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        return _extract_response(response.json())
    except requests.exceptions.HTTPError as http_err:
        content = None
        try:
            content = response.json()
        except Exception:
            content = response.text
        return {"error": str(http_err), "body": content, "url": foundry_url}
    except Exception as e:
        return {"error": str(e), "url": foundry_url}
