from datetime import date

import anyio

from backend.app.agent import Agent, SafetyDecision, SafetyVerdict
from backend.app.agent.prompts import ONBOARDING_GUIDANCE, profile_context
from backend.app.llm_client import LLMClient, LLMResult, MockLLMClient, ToolCall
from backend.app.storage import FileStorage, UserProfile


def _allow(_message: str) -> SafetyVerdict:
    return SafetyVerdict(decision=SafetyDecision.ALLOW)


class _CapturingLLM(LLMClient):
    def __init__(self):
        self.messages = None

    def complete(self, messages, *, tools=None, response_schema=None):
        self.messages = messages
        return LLMResult(text="ok")


def _system_text(llm) -> str:
    return " ".join(m["content"] for m in llm.messages if m.get("role") == "system")


def test_profile_context_none_is_onboarding():
    assert profile_context(None) == ONBOARDING_GUIDANCE


def test_profile_context_summarizes_existing():
    txt = profile_context(UserProfile(nickname="Bo", preferences=["walks"], locality="Brno"))
    assert "Bo" in txt
    assert "walks" in txt
    assert "Brno" in txt


def test_onboarding_context_when_no_profile(tmp_path):
    llm = _CapturingLLM()
    anyio.run(Agent(FileStorage(tmp_path), llm, safety=_allow).run, "hello")
    text = _system_text(llm).lower()
    assert "optional" in text  # locality/age/social env disclaimer
    assert "skip" in text


def test_profile_summary_injected_when_present(tmp_path):
    storage = FileStorage(tmp_path)
    storage.save_profile(UserProfile(nickname="Aleš", preferences=["self-care"]))
    llm = _CapturingLLM()
    anyio.run(Agent(storage, llm, safety=_allow).run, "what now?")
    text = _system_text(llm)
    assert "Aleš" in text
    assert "self-care" in text


def test_onboarding_persists_profile_with_optionals_skipped(tmp_path):
    storage = FileStorage(tmp_path)
    llm = MockLLMClient(
        [
            LLMResult(
                tool_calls=[
                    ToolCall(
                        "c1",
                        "upsert_profile",
                        {"nickname": "Aleš", "preferences": ["help elderly"]},
                    )
                ]
            ),
            LLMResult(text="You're all set!"),
        ]
    )
    res = anyio.run(Agent(storage, llm, safety=_allow).run, "I'm new here")
    assert res.tools_called == ["upsert_profile"]
    profile = storage.load_profile()
    assert profile.nickname == "Aleš"
    assert profile.preferences == ["help elderly"]
    assert profile.locality is None and profile.age is None  # optionals skipped
    assert profile.version == 1


def test_profile_update_bumps_version(tmp_path):
    storage = FileStorage(tmp_path)
    storage.save_profile(UserProfile(nickname="Aleš"))  # v1
    llm = MockLLMClient(
        [
            LLMResult(
                tool_calls=[ToolCall("c1", "upsert_profile", {"nickname": "Aleš", "age": 30})]
            ),
            LLMResult(text="Updated!"),
        ]
    )
    anyio.run(Agent(storage, llm, safety=_allow).run, "I'm 30 now")
    profile = storage.load_profile()
    assert profile.version == 2
    assert profile.age == 30


def test_today_date_in_system_context(tmp_path):
    llm = _CapturingLLM()
    anyio.run(Agent(FileStorage(tmp_path), llm, safety=_allow).run, "hi")
    assert date.today().isoformat() in _system_text(llm)
