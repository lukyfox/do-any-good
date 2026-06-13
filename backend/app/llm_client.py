import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from typing import Any, Dict, Optional
import json
import re
import ast

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
        val = payload["response"]
        # If the response is a string containing JSON or a Python dict, attempt to parse it
        if isinstance(val, str):
            try:
                parsed_val = json.loads(val)
                return _extract_response(parsed_val) if isinstance(parsed_val, dict) else parsed_val
            except Exception:
                # Try to eval as Python literal
                try:
                    parsed_val = ast.literal_eval(val)
                    return _extract_response(parsed_val) if isinstance(parsed_val, dict) else parsed_val
                except Exception:
                    # Fallback: extract the last {...} block and try again
                    m = re.search(r"(\{[\s\S]*\})", val)
                    if m:
                        candidate = m.group(1)
                        try:
                            parsed_val = ast.literal_eval(candidate)
                            return _extract_response(parsed_val) if isinstance(parsed_val, dict) else parsed_val
                        except Exception:
                            try:
                                return json.loads(candidate)
                            except Exception:
                                return val
                    return val
        return val

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
    """Attempt to find and parse JSON in a text blob. Returns parsed JSON or None on failure."""
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


def _parse_suggestion_text(text: str) -> Dict[str, Any]:
    """Heuristic parser to extract structured fields from suggestion text."""
    out: Dict[str, Any] = {"title": None, "description": None, "why": None, "how": None, "bonus": None, "text": text}
    # Normalize separators
    t = text.replace('\r\n', '\n')
    # Try to find a title line like '**Good Deed:**' or a first bold heading
    title_m = re.search(r"\*\*(.*?)\*\*", t)
    if title_m:
        out["title"] = title_m.group(1).strip()

    # Split by common section headings
    sections = re.split(r"\n-{3,}\n|\n\*\*|\n\n", t)
    # Look for keywords
    for sec in sections:
        s = sec.strip()
        if not s:
            continue
        low = s.lower()
        if "why" in low and not out["why"]:
            out["why"] = s
        elif "how to" in low and not out["how"]:
            out["how"] = s
        elif "bonus" in low and not out["bonus"]:
            out["bonus"] = s
        elif ("good deed" in low or "good deed:" in low or out["description"] is None) and out["description"] is None:
            out["description"] = s

    return out


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


def get_structured_response(question: str, request_class: str) -> Dict[str, Any]:
    """Call the LLM and return a structured dict with suggestions.

    Returns: { original: <raw response>, parsed: <parsed JSON if any>, suggestions: [ {title, description, why, how, bonus, text} ] }
    """
    resp = call_foundry_responses(question, request_class)
    result: Dict[str, Any] = {"original": resp, "parsed": None, "suggestions": []}

    # Extract parsed and raw_text from response
    parsed = None
    raw_text = None
    if isinstance(resp, dict):
        if "parsed" in resp:
            parsed = resp.get("parsed")
        if "raw" in resp:
            raw_text = resp.get("raw")
        # Azure-style direct payload
        if not raw_text and "content" in resp and isinstance(resp["content"], list):
            texts = []
            for item in resp["content"]:
                if isinstance(item, dict) and item.get("type") == "output_text":
                    texts.append(item.get("text", ""))
            raw_text = "\n".join(texts) if texts else raw_text
    elif isinstance(resp, str):
        raw_text = resp

    result["parsed"] = parsed

    # If parsed contains suggestions list, use them
    if isinstance(parsed, dict):
        for key in ("suggestions", "items", "results"):
            if key in parsed and isinstance(parsed[key], list):
                for item in parsed[key]:
                    if isinstance(item, str):
                        result["suggestions"].append(_parse_suggestion_text(item))
                    elif isinstance(item, dict):
                        text = item.get("text") or item.get("title") or json.dumps(item)
                        parsed_item = _parse_suggestion_text(str(text))
                        parsed_item.update({k: v for k, v in item.items() if k not in parsed_item})
                        result["suggestions"].append(parsed_item)
                return result

    # If we have raw_text, split by bullets or paragraphs
    if raw_text:
        items = re.findall(r"(?m)^(?:\d+\.|-|•)\s*(.+)$", raw_text)
        if items:
            for it in items:
                result["suggestions"].append(_parse_suggestion_text(it.strip()))
            return result

        # Otherwise split by double newlines
        parts = [p.strip() for p in re.split(r"\n\s*\n", raw_text) if p.strip()]
        if parts and len(parts[0]) < 120 and (parts[0].lower().startswith("good deed") or "suggestion" in parts[0].lower()):
            parts = parts[1:]
        for p in parts:
            if len(p) < 20:
                continue
            result["suggestions"].append(_parse_suggestion_text(p))
        if result["suggestions"]:
            return result

    # Fallback: return raw as single suggestion
    if raw_text:
        result["suggestions"].append({"text": raw_text})
    return result
