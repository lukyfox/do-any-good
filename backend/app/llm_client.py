import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from typing import Any, Dict, Optional

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

FOUNDARY_URL = os.getenv("FOUNDRY_RESPONSES_URL")
API_KEY = os.getenv("FOUNDRY_API_KEY")
FOUNDRY_PROJECT = os.getenv("FOUNDRY_PROJECT")


def _mock_response(question: str, request_class: str) -> Dict[str, Any]:
    return {
        "text": f"Mocked Foundry response for '{question}' (class={request_class}).",
        "suggestions": [
            {"title": "Help a neighbor", "age_suitability": "all", "location_needed": False},
            {"title": "Plant local trees", "age_suitability": "18+", "location_needed": True},
        ],
    }


def _extract_response(payload: Dict[str, Any]) -> Any:
    if "response" in payload:
        return payload["response"]
    if "output" in payload:
        output = payload["output"]
        if isinstance(output, list):
            return "\n".join(str(item) for item in output)
        return output
    return payload


def call_foundry_responses(question: str, request_class: str) -> Any:
    """Call Microsoft Foundry Responses API, or return a mock response when not configured."""
    if not FOUNDARY_URL or not API_KEY:
        return _mock_response(question, request_class)

    payload: Dict[str, Any] = {
        "input": question,
        "requestClass": request_class,
    }
    if FOUNDRY_PROJECT:
        payload["project"] = FOUNDRY_PROJECT

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(FOUNDARY_URL, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        return _extract_response(response.json())
    except Exception as e:
        return {"error": str(e)}
