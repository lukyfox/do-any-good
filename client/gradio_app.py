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


def respond(user_input, history, to_mcp=False):
    history = history or []
    history.append(("User", user_input))
    if to_mcp:
        resp = call_mcp(user_input)
        assistant_text = resp.get("response") if isinstance(resp, dict) else str(resp)
        if isinstance(assistant_text, dict):
            assistant_text = assistant_text.get("text") or str(assistant_text)
    else:
        assistant_text = "I can forward this to MCP or run a local tool. Click 'Send to MCP' to ask the model."
    history.append(("Assistant", assistant_text))
    return "", history


def start_ui():
    with gr.Blocks() as demo:
        gr.Markdown("# Goodies Suggester — Gradio Client")
        chatbot = gr.Chatbot()
        txt = gr.Textbox(show_label=False, placeholder="Type your message and press Send")
        with gr.Row():
            send = gr.Button("Send")
            send_mcp = gr.Button("Send to MCP")
            tool_btn = gr.Button("Get time (tool)")

        send.click(lambda inp, h: respond(inp, h, to_mcp=False), [txt, chatbot], [txt, chatbot])
        send_mcp.click(lambda inp, h: respond(inp, h, to_mcp=True), [txt, chatbot], [txt, chatbot])
        def run_tool(h):
            h = h or []
            h.append(("Tool", local_tool_get_time()))
            return "", h
        tool_btn.click(run_tool, [chatbot], [txt, chatbot])

        demo.launch()


if __name__ == "__main__":
    start_ui()
