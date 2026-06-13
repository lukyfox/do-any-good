"""Interim HTTP backend for the Gradio client.

This thin endpoint is the M0 baseline. M4 replaces it with the agent `/chat`
endpoint backed by the MCP tools server.
"""
from fastapi import FastAPI
from pydantic import BaseModel

from .llm_client import get_structured_response

app = FastAPI(title="Do Any Good — interim backend")


class ProcessRequest(BaseModel):
    question: str
    request_class: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp/process")
async def process(req: ProcessRequest) -> dict:
    return get_structured_response(req.question, req.request_class)
