from fastapi import FastAPI
from pydantic import BaseModel
from .llm_client import call_foundry_responses

app = FastAPI(title="MCP FastAPI Server")


class MCPRequest(BaseModel):
    question: str
    request_class: str


@app.post("/mcp/process")
async def process(req: MCPRequest):
    """Receive a question and request class, forward to LLM, return response."""
    resp = call_foundry_responses(req.question, req.request_class)
    return {"response": resp}
