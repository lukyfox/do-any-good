from fastapi.testclient import TestClient

from backend.app.llm_client import LLMResult, MockLLMClient, ToolCall
from backend.app.main import app, get_agent_llm, get_storage
from backend.app.storage import FileStorage


def test_full_journey(tmp_path):
    """Onboard -> plan a week -> complete a Goody -> overview reflects it."""
    storage = FileStorage(tmp_path)
    weekly = {"suggestions": [{"title": f"Deed {i}", "category": "others"} for i in range(7)]}
    llm = MockLLMClient(
        [
            # /chat: safety verdict, a tool call saving the profile, then the reply
            LLMResult(parsed={"decision": "allow", "reason": "", "resources": []}),
            LLMResult(
                tool_calls=[
                    ToolCall(
                        "c1",
                        "upsert_profile",
                        {"nickname": "Aleš", "preferences": ["help elderly"]},
                    )
                ]
            ),
            LLMResult(text="Welcome, Aleš! I've saved your profile."),
            # /plan/week: a 7-day structured plan (all 'others' -> self enforced by the backend)
            LLMResult(parsed=weekly),
        ]
    )
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_agent_llm] = lambda: llm
    try:
        client = TestClient(app)

        # 1. Onboarding via chat persists the profile through the MCP tool.
        chat = client.post("/chat", json={"message": "Hi, I'm Aleš", "history": []}).json()
        assert "Aleš" in chat["reply"]
        assert storage.load_profile().nickname == "Aleš"

        # 2. Weekly plan: 7 planned Goodies, at least one for the user themselves.
        goodies = client.post("/plan/week").json()["goodies"]
        assert len(goodies) == 7
        assert any(g["category"] == "self" for g in goodies)

        # 3. Complete the first planned Goody with a summary.
        planned = client.get("/goodies", params={"status": "planned"}).json()["goodies"]
        assert len(planned) == 7
        done = client.post(
            f"/goodies/{planned[0]['id']}/status",
            json={"status": "done", "summary": "Felt great."},
        ).json()
        assert done["status"] == "done"
        assert done["user_summary"] == "Felt great."

        # 4. Overview reflects the completion.
        overview = client.get("/overview").json()
        assert overview["counts"]["total"] == 7
        assert overview["counts"]["done"] == 1
        assert overview["counts"]["planned"] == 6
    finally:
        app.dependency_overrides.clear()
