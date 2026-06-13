"""Gradio chat client for the Do Any Good interim backend.

M0 baseline: a clean chat UI that forwards a message to the backend and renders
the reply. Profile onboarding, suggestions, and tracking affordances arrive in M9.
"""
from __future__ import annotations

import os
from typing import Any

import gradio as gr
import requests

BACKEND_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp/process")
REQUEST_TIMEOUT_SECONDS = 30


def call_backend(question: str, request_class: str = "goodies_suggester") -> dict[str, Any]:
    """POST a message to the backend and return the parsed JSON envelope."""
    try:
        r = requests.post(
            BACKEND_URL,
            json={"question": question, "request_class": request_class},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as err:
        return {"error": str(err)}


def assistant_text(resp: dict[str, Any]) -> str:
    """Extract a human-readable string from the backend's response envelope."""
    if not isinstance(resp, dict):
        return str(resp)
    if "error" in resp:
        return f"Error: {resp['error']}"

    payload = resp.get("response", resp)
    if isinstance(payload, dict):
        if isinstance(payload.get("text"), str):
            return payload["text"]
        suggestions = payload.get("suggestions")
        if isinstance(suggestions, list) and suggestions:
            lines = []
            for item in suggestions:
                if isinstance(item, dict):
                    lines.append(str(item.get("title") or item.get("text") or item))
                else:
                    lines.append(str(item))
            return "\n".join(f"- {line}" for line in lines)
    return str(payload)


def respond(user_input: str, history: list[dict[str, str]]):
    """Append the exchange to history and return updated chat state."""
    history = (history or []) + [{"role": "user", "content": user_input}]
    reply = assistant_text(call_backend(user_input))
    history = history + [{"role": "assistant", "content": reply}]
    return "", history, history


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Do Any Good") as demo:
        gr.Markdown("# Do Any Good — chat (interim)")
        # gradio 6 renders the messages format ({"role", "content"}) by default.
        chatbot = gr.Chatbot()
        state = gr.State([])
        txt = gr.Textbox(show_label=False, placeholder="Type your message and press Send")
        send = gr.Button("Send")

        send.click(respond, [txt, state], [txt, chatbot, state])
        txt.submit(respond, [txt, state], [txt, chatbot, state])
    return demo


if __name__ == "__main__":
    build_ui().launch()
