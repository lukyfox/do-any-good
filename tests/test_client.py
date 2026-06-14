from fastapi.testclient import TestClient

from backend.app.llm_client import LLMResult, MockLLMClient
from backend.app.main import app, get_agent_llm, get_storage
from backend.app.storage import FileStorage
from client import gradio_app

# --- pure formatting helpers ----------------------------------------------


def test_format_goody():
    md = gradio_app.format_goody({"title": "Walk", "category": "self", "description": "A walk"})
    assert "Walk" in md and "self" in md and "A walk" in md


def test_format_plan_numbers_items():
    md = gradio_app.format_plan(
        [{"title": "A", "category": "others"}, {"title": "B", "category": "self"}]
    )
    assert "1." in md and "2." in md and "A" in md and "B" in md


def test_format_plan_empty():
    assert "No suggestions" in gradio_app.format_plan([])


def test_format_overview():
    data = {
        "counts": {"total": 2, "planned": 1, "done": 1, "missed": 0, "self": 1, "others": 1},
        "planned": [{"date": "2026-06-14", "title": "A"}],
        "done": [{"date": "2026-06-13", "title": "B"}],
        "missed": [],
    }
    md = gradio_app.format_overview(data)
    assert "planned 1" in md and "done 1" in md
    assert "A" in md and "B" in md


def test_format_overview_handles_error():
    assert "No data" in gradio_app.format_overview({"error": "down"})


def test_planned_choices():
    choices = gradio_app.planned_choices(
        [{"id": "1", "date": "2026-06-14", "title": "A"}, {"title": "no id"}]
    )
    assert choices == [("2026-06-14 - A", "1")]


def test_format_goody_shows_link():
    md = gradio_app.format_goody(
        {"title": "X", "category": "others", "link": "https://donio.cz/x"}
    )
    assert "https://donio.cz/x" in md


def test_format_overview_shows_link():
    data = {
        "counts": {"total": 1, "planned": 1, "done": 0, "missed": 0, "self": 0, "others": 1},
        "planned": [{"date": "2026-06-14", "title": "Campaign", "link": "https://donio.cz/x"}],
        "done": [],
        "missed": [],
    }
    md = gradio_app.format_overview(data)
    assert "(https://donio.cz/x)" in md  # rendered as a markdown link


# --- HTTP wrappers (mocked transport) -------------------------------------


def test_chat_calls_backend(monkeypatch):
    captured = {}

    def fake(method, path, *, json=None, params=None):
        captured.update(method=method, path=path, json=json)
        return {"reply": "x", "history": []}

    monkeypatch.setattr(gradio_app, "_request", fake)
    out = gradio_app.chat("hello", [{"role": "user", "content": "prev"}])
    assert captured["method"] == "POST"
    assert captured["path"] == "/chat"
    assert captured["json"]["message"] == "hello"
    assert out["reply"] == "x"


def test_request_returns_error_on_failure(monkeypatch):
    def boom(*a, **k):
        raise gradio_app.requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(gradio_app.requests, "request", boom)
    assert "error" in gradio_app._request("GET", "/overview")


# --- end-to-end via in-process backend ------------------------------------


def _route_to_testclient(monkeypatch, client):
    def fake(method, path, *, json=None, params=None):
        return client.request(method, path, json=json, params=params).json()

    monkeypatch.setattr(gradio_app, "_request", fake)


def test_e2e_chat(tmp_path, monkeypatch):
    app.dependency_overrides[get_storage] = lambda: FileStorage(tmp_path)
    app.dependency_overrides[get_agent_llm] = lambda: MockLLMClient(
        [
            LLMResult(parsed={"decision": "allow", "reason": "", "resources": []}),
            LLMResult(text="Ahoj!"),
        ]
    )
    try:
        _route_to_testclient(monkeypatch, TestClient(app))
        result = gradio_app.chat("Hi", [])
        assert result["reply"] == "Ahoj!"
        assert result["history"][-1]["content"] == "Ahoj!"
    finally:
        app.dependency_overrides.clear()


def test_e2e_plan_week_enforces_self(tmp_path, monkeypatch):
    plan = {"suggestions": [{"title": f"D{i}", "category": "others"} for i in range(7)]}
    app.dependency_overrides[get_storage] = lambda: FileStorage(tmp_path)
    app.dependency_overrides[get_agent_llm] = lambda: MockLLMClient([LLMResult(parsed=plan)])
    try:
        _route_to_testclient(monkeypatch, TestClient(app))
        goodies = gradio_app.plan_week()["goodies"]
        assert len(goodies) == 7
        assert any(g["category"] == "self" for g in goodies)
    finally:
        app.dependency_overrides.clear()


def test_delete_goody_calls_backend(monkeypatch):
    captured = {}

    def fake(method, path, *, json=None, params=None):
        captured.update(method=method, path=path)
        return {"deleted": "abc"}

    monkeypatch.setattr(gradio_app, "_request", fake)
    out = gradio_app.delete_goody("abc")
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/goodies/abc"
    assert out["deleted"] == "abc"


def test_build_ui_constructs():
    assert gradio_app.build_ui() is not None
