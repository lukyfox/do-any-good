from datetime import date

from fastapi.testclient import TestClient

from backend.app.agent import Agent
from backend.app.agent.suggestions import (
    DEFAULT_SELF_GOODY,
    GoodySuggestion,
    ensure_self_balance,
    persist_plan,
    suggest_daily,
    suggest_weekly,
)
from backend.app.llm_client import LLMResult, MockLLMClient
from backend.app.main import app, get_agent_llm, get_storage
from backend.app.storage import FileStorage, GoodyCategory, GoodyStatus


def _others(title):
    return GoodySuggestion(title=title, category=GoodyCategory.OTHERS)


def _all_others_plan():
    return {"suggestions": [{"title": f"D{i}", "category": "others"} for i in range(7)]}


def test_ensure_self_balance_keeps_existing_self():
    items = [_others("a"), GoodySuggestion(title="me", category=GoodyCategory.SELF)]
    assert ensure_self_balance(items) == items


def test_ensure_self_balance_adds_self_when_missing():
    result = ensure_self_balance([_others("a"), _others("b")])
    assert any(s.category == GoodyCategory.SELF for s in result)
    assert len(result) == 2  # count preserved (last replaced)


def test_ensure_self_balance_empty():
    assert ensure_self_balance([]) == [DEFAULT_SELF_GOODY]


def test_suggest_daily_parses():
    llm = MockLLMClient([LLMResult(parsed={"title": "Walk", "category": "self"})])
    suggestion = suggest_daily(llm, None)
    assert suggestion.title == "Walk"
    assert suggestion.category == GoodyCategory.SELF


def test_suggest_daily_fallback_on_bad_parse():
    llm = MockLLMClient([LLMResult(text="not structured")])
    assert suggest_daily(llm, None) == DEFAULT_SELF_GOODY


def test_suggest_weekly_enforces_self():
    llm = MockLLMClient([LLMResult(parsed=_all_others_plan())])
    result = suggest_weekly(llm, None)
    assert len(result) == 7
    assert any(s.category == GoodyCategory.SELF for s in result)


def test_persist_plan_sets_dates_and_status(tmp_path):
    storage = FileStorage(tmp_path)
    suggestions = [_others("a"), GoodySuggestion(title="me", category=GoodyCategory.SELF)]
    goodies = persist_plan(storage, suggestions, date(2026, 6, 14))
    assert [g.date.isoformat() for g in goodies] == ["2026-06-14", "2026-06-15"]
    assert all(g.status == GoodyStatus.PLANNED for g in goodies)
    assert len(storage.list_goodies()) == 2  # persisted


def test_agent_suggest_week_persists(tmp_path):
    storage = FileStorage(tmp_path)
    agent = Agent(storage, MockLLMClient([LLMResult(parsed=_all_others_plan())]))
    goodies = agent.suggest_week(start=date(2026, 6, 14))
    assert len(goodies) == 7
    assert any(g.category == GoodyCategory.SELF for g in goodies)
    assert all(g.status == GoodyStatus.PLANNED for g in storage.list_goodies())


def test_plan_week_endpoint(tmp_path):
    app.dependency_overrides[get_storage] = lambda: FileStorage(tmp_path)
    app.dependency_overrides[get_agent_llm] = lambda: MockLLMClient(
        [LLMResult(parsed=_all_others_plan())]
    )
    try:
        r = TestClient(app).post("/plan/week")
        assert r.status_code == 200
        goodies = r.json()["goodies"]
        assert len(goodies) == 7
        assert any(g["category"] == "self" for g in goodies)
    finally:
        app.dependency_overrides.clear()
