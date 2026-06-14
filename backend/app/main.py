"""HTTP backend for the Gradio client.

Exposes the agent at /chat (buffered) and /chat/stream (token streaming), plus
suggestion and tracking endpoints.
"""
from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .agent import Agent
from .config import get_settings
from .llm_client import LLMClient, get_llm_client
from .overview import build_overview
from .storage import FileStorage, GoodyNotFoundError, GoodyStatus, JournalEntry

app = FastAPI(title="Do Any Good backend")


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None


class StatusUpdate(BaseModel):
    status: GoodyStatus
    summary: str | None = None


class JournalAppend(BaseModel):
    text: str
    title: str | None = None
    goody_id: str | None = None


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


@app.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    storage: Annotated[FileStorage, Depends(get_storage)],
    llm: Annotated[LLMClient, Depends(get_agent_llm)],
) -> StreamingResponse:
    async def deltas():
        async for delta in Agent(storage, llm).run_stream(req.message, req.history):
            yield delta

    return StreamingResponse(deltas(), media_type="text/plain; charset=utf-8")


@app.post("/plan/today")
async def plan_today(
    storage: Annotated[FileStorage, Depends(get_storage)],
    llm: Annotated[LLMClient, Depends(get_agent_llm)],
) -> dict:
    goody = Agent(storage, llm).suggest_today()
    return {"goody": goody.model_dump(mode="json")}


@app.post("/plan/week")
async def plan_week(
    storage: Annotated[FileStorage, Depends(get_storage)],
    llm: Annotated[LLMClient, Depends(get_agent_llm)],
) -> dict:
    goodies = Agent(storage, llm).suggest_week()
    return {"goodies": [g.model_dump(mode="json") for g in goodies]}


@app.get("/goodies")
async def get_goodies(
    storage: Annotated[FileStorage, Depends(get_storage)],
    status: GoodyStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    goodies = storage.list_goodies(status=status, date_from=date_from, date_to=date_to)
    return {"goodies": [g.model_dump(mode="json") for g in goodies]}


@app.post("/goodies/{goody_id}/status")
async def update_goody_status(
    goody_id: str,
    body: StatusUpdate,
    storage: Annotated[FileStorage, Depends(get_storage)],
) -> dict:
    try:
        goody = storage.set_goody_status(goody_id, body.status, body.summary)
    except GoodyNotFoundError as err:
        raise HTTPException(status_code=404, detail="Goody not found") from err
    return goody.model_dump(mode="json")


@app.delete("/goodies/{goody_id}")
async def delete_goody(
    goody_id: str,
    storage: Annotated[FileStorage, Depends(get_storage)],
) -> dict:
    try:
        storage.delete_goody(goody_id)
    except GoodyNotFoundError as err:
        raise HTTPException(status_code=404, detail="Goody not found") from err
    return {"deleted": goody_id}


@app.get("/overview")
async def get_overview(storage: Annotated[FileStorage, Depends(get_storage)]) -> dict:
    return build_overview(storage)


@app.post("/journal")
async def add_journal(
    body: JournalAppend,
    storage: Annotated[FileStorage, Depends(get_storage)],
) -> dict:
    entry = storage.append_journal(
        JournalEntry(text=body.text, title=body.title, goody_id=body.goody_id)
    )
    return entry.model_dump(mode="json")


@app.get("/journal")
async def get_journal(storage: Annotated[FileStorage, Depends(get_storage)]) -> dict:
    return {"markdown": storage.read_journal()}
