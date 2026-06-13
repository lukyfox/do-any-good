"""Gradio client for the Do Any Good backend.

Talks to the agent over HTTP: chat (/chat), suggestions (/plan/*), and tracking
(/goodies, /overview). All requests go through `_request`, which tests reroute
to an in-process TestClient.
"""
from __future__ import annotations

import os

import gradio as gr
import requests

BACKEND_URL = os.getenv("DAG_BACKEND_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT_SECONDS = 60


def _request(
    method: str, path: str, *, json: dict | None = None, params: dict | None = None
) -> dict:
    try:
        r = requests.request(
            method, f"{BACKEND_URL}{path}", json=json, params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as err:
        return {"error": str(err)}


# --- backend calls ---------------------------------------------------------


def chat(message: str, history: list[dict]) -> dict:
    return _request("POST", "/chat", json={"message": message, "history": history})


def plan_today() -> dict:
    return _request("POST", "/plan/today")


def plan_week() -> dict:
    return _request("POST", "/plan/week")


def list_goodies(status: str | None = None) -> dict:
    return _request("GET", "/goodies", params={"status": status} if status else None)


def set_status(goody_id: str, status: str, summary: str) -> dict:
    return _request(
        "POST", f"/goodies/{goody_id}/status",
        json={"status": status, "summary": summary or None},
    )


def overview() -> dict:
    return _request("GET", "/overview")


# --- pure formatting helpers ----------------------------------------------


def format_goody(goody: dict) -> str:
    if not isinstance(goody, dict):
        return str(goody)
    title = goody.get("title", "(untitled)")
    category = goody.get("category", "")
    line = f"**{title}**" + (f" _({category})_" if category else "")
    description = goody.get("description")
    return f"{line}\n{description}" if description else line


def format_plan(goodies: list[dict]) -> str:
    if not goodies:
        return "_No suggestions._"
    rows = []
    for i, goody in enumerate(goodies, start=1):
        date = goody.get("date")
        rows.append(f"{i}. {format_goody(goody)}" + (f"  \n*{date}*" if date else ""))
    return "\n\n".join(rows)


def format_overview(data: dict) -> str:
    if not isinstance(data, dict) or "counts" not in data:
        return "_No data yet._"
    c = data["counts"]
    lines = [
        f"**Goodies**: planned {c['planned']}, done {c['done']}, missed {c['missed']} "
        f"(self {c['self']} / others {c['others']})",
    ]
    for status in ("planned", "done", "missed"):
        items = data.get(status, [])
        if items:
            lines.append(f"\n**{status.capitalize()}:**")
            lines += [f"- {g.get('date', '')}: {g.get('title', '')}" for g in items]
    return "\n".join(lines)


def planned_choices(goodies: list[dict]) -> list[tuple[str, str]]:
    return [
        (f"{g.get('date', '')} - {g.get('title', '')}", g["id"]) for g in goodies if g.get("id")
    ]


# --- UI --------------------------------------------------------------------


def _assistant(history: list[dict], text: str) -> list[dict]:
    return history + [{"role": "assistant", "content": text}]


def _overview_md() -> str:
    return format_overview(overview())


def _planned_update():
    return gr.update(choices=planned_choices(list_goodies(status="planned").get("goodies", [])))


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Do Any Good") as demo:
        gr.Markdown("# Do Any Good\nDo one good deed a day - a *Goody*.")
        state = gr.State([])
        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(label="Chat")
                txt = gr.Textbox(show_label=False, placeholder="Talk to your DAG assistant...")
                with gr.Row():
                    send = gr.Button("Send", variant="primary")
                    today_btn = gr.Button("Suggest today's Goody")
                    week_btn = gr.Button("Plan my week")
            with gr.Column(scale=2):
                overview_md = gr.Markdown("_No data yet._")
                refresh_btn = gr.Button("Refresh overview")
                gr.Markdown("### Record a Goody")
                goody_dd = gr.Dropdown(label="Planned Goody", choices=[])
                status_radio = gr.Radio(["done", "missed"], value="done", label="Status")
                summary_box = gr.Textbox(label="Your summary (optional)")
                record_btn = gr.Button("Record")

        def on_send(message, history):
            if message and message.strip():
                result = chat(message, history)
                history = result.get("history") or _assistant(history, result.get("error", "..."))
            return "", history, history, _overview_md(), _planned_update()

        def on_today(history):
            result = plan_today()
            goody = result.get("goody")
            body = format_goody(goody) if goody else result.get("error", "(failed)")
            history = _assistant(history, f"Today's Goody:\n\n{body}")
            return history, history, _overview_md(), _planned_update()

        def on_week(history):
            result = plan_week()
            goodies = result.get("goodies")
            body = format_plan(goodies) if goodies else result.get("error", "(failed)")
            history = _assistant(history, f"Your week:\n\n{body}")
            return history, history, _overview_md(), _planned_update()

        def on_record(goody_id, status, summary, history):
            if goody_id:
                result = set_status(goody_id, status, summary)
                label = result.get("title", goody_id) if "error" not in result else result["error"]
                history = _assistant(history, f"Recorded **{label}** as {status}.")
            return history, history, _overview_md(), _planned_update(), ""

        chat_outputs = [txt, chatbot, state, overview_md, goody_dd]
        send.click(on_send, [txt, state], chat_outputs)
        txt.submit(on_send, [txt, state], chat_outputs)
        today_btn.click(on_today, [state], [chatbot, state, overview_md, goody_dd])
        week_btn.click(on_week, [state], [chatbot, state, overview_md, goody_dd])
        refresh_btn.click(
            lambda: (_overview_md(), _planned_update()), None, [overview_md, goody_dd]
        )
        record_btn.click(
            on_record,
            [goody_dd, status_radio, summary_box, state],
            [chatbot, state, overview_md, goody_dd, summary_box],
        )
    return demo


if __name__ == "__main__":
    build_ui().launch()
