# Goodies Suggester — MCP + Gradio MVP

This repository contains a minimal MVP for an AI-powered "good deeds" suggester using:

- FastAPI for the MCP server
- A small LLM client wrapper intended to call Microsoft Foundry Responses API (or return a mock if not configured)
- Gradio client for chatting, calling tools, and forwarding requests to the MCP endpoint

Quick start (create a virtualenv first):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# In one terminal: start the MCP server
python -m uvicorn backend.app.main:app --reload
# In another terminal: start the client
python client\gradio_app.py
```

Configuration (optional):

Create a `.env` with the following values (or export env vars):

- `FOUNDRY_RESPONSES_URL` — full URL to the Foundry Responses endpoint
- `FOUNDRY_API_KEY` — API key or bearer token for Foundry
- `FOUNDRY_PROJECT` — Foundry project name or ID (optional)
- `MCP_SERVER_URL` — URL of the MCP server (defaults to http://localhost:8000/mcp/process)

Notes:

- The LLM client in `backend/app/llm_client.py` now sends `input`, `requestClass`, and optional `project` to Foundry.
- If `FOUNDRY_RESPONSES_URL` or `FOUNDRY_API_KEY` are missing, the backend falls back to a mock response for local testing.
# do-any-good
AI powered application for personal growth through making good things ;)
