"""HTTP backend for the Gradio client.

Exposes the agent at /chat (M4). The legacy /mcp/process endpoint remains as a
thin interim shim until the client is rebuilt in M9.
"""
from typing import Annotated

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from .agent import Agent
from .config import get_settings
from .llm_client import LLMClient, get_llm_client, get_structured_response
from .storage import FileStorage

app = FastAPI(title="Do Any Good backend")


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None


class ProcessRequest(BaseModel):
    question: str
    request_class: str


def get_storage() -> FileStorage:
    return FileStorage(get_settings().data_dir)


def get_agent_llm() -> LLMClient:
    return get_llm_client()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
async def chat(
    req: ChatRequest,
    storage: Annotated[FileStorage, Depends(get_storage)],
    llm: Annotated[LLMClient, Depends(get_agent_llm)],
) -> dict:
    result = await Agent(storage, llm).run(req.message, req.history)
    return {"reply": result.reply, "history": result.history}


@app.post("/mcp/process")
async def process(req: ProcessRequest) -> dict:
    return get_structured_response(req.question, req.request_class)
