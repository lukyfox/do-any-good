import os
import time
import json
import requests
import gradio as gr

MCP_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp/process")


def call_mcp(question, request_class="goodies_suggester"):
    try:
        r = requests.post(MCP_URL, json={"question": question, "request_class": request_class}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def local_tool_get_time():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _extract_assistant_text(resp):
    if not isinstance(resp, dict):
        return str(resp)

    if "response" in resp:
        return _extract_assistant_text(resp["response"])

    if "text" in resp and isinstance(resp["text"], str):
        return resp["text"]

    if "raw" in resp and isinstance(resp["raw"], str):
        return resp["raw"]

    if "suggestions" in resp and isinstance(resp["suggestions"], list):
        lines = []
        for item in resp["suggestions"]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("text") or ""
                description = item.get("description")
                if title and description:
                    lines.append(f"{title}: {description}")
                elif title:
                    lines.append(str(title))
                elif description:
                    lines.append(str(description))
            else:
                lines.append(str(item))
        if lines:
            return "\n\n".join(lines)

    if "parsed" in resp:
        parsed = resp["parsed"]
        if isinstance(parsed, str):
            return parsed
        if isinstance(parsed, dict) and "text" in parsed and isinstance(parsed["text"], str):
            return parsed["text"]
        if isinstance(parsed, dict):
            return json.dumps(parsed, ensure_ascii=False)

    if "error" in resp:
        return str(resp["error"])

    for key in ("message", "content", "result"):
        if key in resp and isinstance(resp[key], str):
            return resp[key]

    return json.dumps(resp, ensure_ascii=False)


def client_agent_decision(user_input, history):
    """Use a small AI-based decision agent to choose routing.

    The agent will try a lightweight local heuristic first. If uncertain,
    it will ask MCP for a short decision and interpret the answer.
    Returns: "tool" or "mcp"
    """
    normalized = user_input.strip().lower()
    tool_triggers = ["time", "current time", "what time", "date", "clock"]
    if any(trigger in normalized for trigger in tool_triggers):
        return "tool"

    # Ask MCP for a decision as a fallback (stateless call). The MCP model
    # should return a short instruction like 'CALL_MCP' or 'TOOL'.
    try:
        decision_prompt = (
            "You are a routing assistant. Given the user's message, reply with ONE token: "
            "CALL_MCP if this should be handled by the core MCP service, or TOOL if it can be handled locally. "
            "Do not include any other text.\nUser message: \"" + user_input + "\""
        )
        resp = call_mcp(decision_prompt, request_class="decision")
        assistant_text = _extract_assistant_text(resp)
        if assistant_text:
            s = str(assistant_text).lower()
            if "call_mcp" in s or "call mcp" in s or "mcp" in s or "call" in s:
                return "mcp"
            if "tool" in s or "time" in s:
                return "tool"
    except Exception:
        pass

    # Default to MCP when unsure
    return "mcp"


def respond(user_input, history_state):
    history_state = history_state or []
    history_state.append({"role": "user", "content": user_input})
    decision = client_agent_decision(user_input, history_state)
    rationale = None
    if decision == "tool":
        assistant_text = local_tool_get_time()
        rationale = "Matched local tool trigger"
    else:
        # When asking MCP for content, the decision agent may have already asked MCP
        resp = call_mcp(user_input)
        assistant_text = _extract_assistant_text(resp)
        rationale = "Routed to MCP for full answer"
    history_state.append({"role": "assistant", "content": assistant_text})
    return "", history_state, history_state, decision, rationale


def start_ui():
    with gr.Blocks() as demo:
        gr.Markdown("# Goodies Suggester — Gradio Client")
        chatbot = gr.Chatbot()
        txt = gr.Textbox(show_label=False, placeholder="Type your message and press Send")
        with gr.Row():
            send = gr.Button("Send")
            log_toggle = gr.Checkbox(label="Enable decision logging", value=False)

        # wrap respond to include logging and rationale display
        state = gr.State([])
        rationale_display = gr.Textbox(label="Decision rationale", lines=4, interactive=False, visible=False)

        def respond_and_maybe_log(inp, h, log_enabled):
            out_txt, out_hist, new_state, decision, rationale = respond(inp, h)
            if log_enabled:
                try:
                    import json, os
                    from datetime import datetime
                    os.makedirs("logs", exist_ok=True)
                    entry = {
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "user_input": inp,
                        "decision": decision,
                        "rationale": rationale,
                    }
                    with open(os.path.join("logs", "decision_log.jsonl"), "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                rationale_text = f"Decision: {decision}\nRationale: {rationale}"
                return out_txt, out_hist, new_state, gr.update(value=rationale_text, visible=True)
            return out_txt, out_hist, new_state, gr.update(value="", visible=False)

        send.click(respond_and_maybe_log, [txt, state, log_toggle], [txt, chatbot, state, rationale_display])

        def toggle_rationale_visibility(log_enabled):
            if log_enabled:
                return gr.update(visible=True, value="")
            return gr.update(visible=False, value="")

        log_toggle.change(toggle_rationale_visibility, [log_toggle], [rationale_display])

        demo.launch()


if __name__ == "__main__":
    start_ui()
