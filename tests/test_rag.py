from datetime import date

import backend.app.rag as rag_mod
from backend.app.agent import Agent
from backend.app.agent.suggestions import GoodySuggestion, goody_to_suggestion, include_rag_match
from backend.app.config import Settings
from backend.app.llm_client import LLMResult, MockLLMClient
from backend.app.rag import NullRagStore, anonymize_profile, get_rag_store, profile_text
from backend.app.storage import FileStorage, Goody, GoodyCategory, UserProfile


class FakeRagStore:
    def __init__(self, match=None):
        self.saved = []
        self._match = match

    def save(self, profile, goody):
        self.saved.append((profile, goody))

    def find_match(self, profile):
        return self._match


def _profile():
    return UserProfile(
        nickname="Aleš", email="a@b.cz", preferences=["help elderly"], locality="Brno", age=34
    )


def test_anonymize_strips_pii():
    anon = anonymize_profile(_profile())
    assert "nickname" not in anon and "email" not in anon
    assert anon["preferences"] == ["help elderly"]
    assert anon["locality"] == "Brno"


def test_profile_text_includes_signal_not_pii():
    text = profile_text(_profile())
    assert "help elderly" in text and "Brno" in text
    assert "Aleš" not in text and "a@b.cz" not in text


def test_null_store_is_noop():
    store = NullRagStore()
    store.save(_profile(), Goody(date=date(2026, 6, 14), title="X", category=GoodyCategory.SELF))
    assert store.find_match(_profile()) is None


def test_get_rag_store_null_when_unconfigured(monkeypatch):
    monkeypatch.setattr(rag_mod, "get_settings", lambda: Settings())
    assert isinstance(get_rag_store(), NullRagStore)


def test_goody_to_suggestion_carries_link_and_note():
    g = Goody(
        date=date(2026, 6, 14),
        title="Donate",
        category=GoodyCategory.OTHERS,
        link="https://donio.cz/x",
    )
    s = goody_to_suggestion(g)
    assert s.title == "Donate"
    assert s.link == "https://donio.cz/x"
    assert s.why  # carries an explanatory note


def test_include_rag_match_replaces_others_keeps_self():
    suggestions = [
        GoodySuggestion(title="A", category=GoodyCategory.OTHERS),
        GoodySuggestion(title="me", category=GoodyCategory.SELF),
        GoodySuggestion(title="B", category=GoodyCategory.OTHERS),
    ]
    match = GoodySuggestion(title="Community", category=GoodyCategory.OTHERS)
    result = include_rag_match(suggestions, match)
    titles = [s.title for s in result]
    assert len(result) == 3
    assert "Community" in titles and "me" in titles


def test_include_rag_match_noop_on_duplicate():
    suggestions = [GoodySuggestion(title="Community", category=GoodyCategory.OTHERS)]
    match = GoodySuggestion(title="Community", category=GoodyCategory.OTHERS)
    assert include_rag_match(suggestions, match) == suggestions


def test_agent_suggest_week_includes_rag_match(tmp_path):
    storage = FileStorage(tmp_path)
    storage.save_profile(_profile())
    match = Goody(date=date(2020, 1, 1), title="Community campaign", category=GoodyCategory.OTHERS)
    plan = {"suggestions": [{"title": f"D{i}", "category": "others"} for i in range(7)]}
    agent = Agent(storage, MockLLMClient([LLMResult(parsed=plan)]), rag=FakeRagStore(match=match))
    titles = [g.title for g in agent.suggest_week(start=date(2026, 6, 14))]
    assert "Community campaign" in titles
