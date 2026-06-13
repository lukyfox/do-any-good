import os
import time
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
        # Extract assistant text
        assistant_text = None
        if isinstance(resp, dict):
            assistant_text = resp.get("response") or resp.get("text") or None
        if isinstance(assistant_text, dict):
            # If the MCP returns structured payload, try to find raw text
            assistant_text = assistant_text.get("text") or assistant_text.get("raw") or assistant_text.get("parsed")
        if isinstance(assistant_text, list):
            assistant_text = " ".join(str(x) for x in assistant_text)
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


def respond(user_input, history):
    history = history or []
    history.append({"role": "user", "content": user_input})
    decision = client_agent_decision(user_input, history)
    if decision == "tool":
        assistant_text = local_tool_get_time()
    else:
        resp = call_mcp(user_input)
        assistant_text = resp.get("response") if isinstance(resp, dict) else str(resp)
        if isinstance(assistant_text, dict):
            assistant_text = assistant_text.get("text") or str(assistant_text)
    history.append({"role": "assistant", "content": assistant_text})
    return "", history


def start_ui():
    with gr.Blocks() as demo:
        gr.Markdown("# Goodies Suggester — Gradio Client")
        chatbot = gr.Chatbot()
        txt = gr.Textbox(show_label=False, placeholder="Type your message and press Send")
        with gr.Row():
            send = gr.Button("Send")

        send.click(respond, [txt, chatbot], [txt, chatbot])

        demo.launch()


if __name__ == "__main__":
    start_ui()
