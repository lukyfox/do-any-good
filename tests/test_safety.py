import anyio

from backend.app.agent import (
    Agent,
    SafetyDecision,
    SafetyVerdict,
    classify_safety,
    refusal_message,
)
from backend.app.llm_client import LLMClient, LLMResult, MockLLMClient
from backend.app.storage import FileStorage


class _BoomLLM(LLMClient):
    def complete(self, messages, *, tools=None, response_schema=None):
        raise AssertionError("LLM must not be called when the request is refused")


class _CapturingLLM(LLMClient):
    def __init__(self):
        self.messages = None

    def complete(self, messages, *, tools=None, response_schema=None):
        self.messages = messages
        return LLMResult(text="ok")


def test_classify_refuse():
    llm = MockLLMClient(
        [
            LLMResult(
                parsed={
                    "decision": "refuse",
                    "reason": "Please seek help",
                    "resources": ["Crisis line 123"],
                }
            )
        ]
    )
    verdict = classify_safety(llm, "I want to hurt myself")
    assert verdict.decision == SafetyDecision.REFUSE
    assert verdict.reason == "Please seek help"
    assert verdict.resources == ["Crisis line 123"]


def test_classify_allow():
    llm = MockLLMClient([LLMResult(parsed={"decision": "allow", "reason": "", "resources": []})])
    assert classify_safety(llm, "help a neighbor").decision == SafetyDecision.ALLOW


def test_classify_defaults_to_allow_on_bad_parse():
    llm = MockLLMClient([LLMResult(text="not json")])
    assert classify_safety(llm, "anything").decision == SafetyDecision.ALLOW


def test_refusal_message_includes_resources():
    msg = refusal_message(
        SafetyVerdict(decision=SafetyDecision.REFUSE, reason="Take care", resources=["988"])
    )
    assert "Take care" in msg
    assert "988" in msg


def test_agent_refuses_and_skips_tools(tmp_path):
    def refuse(_message):
        return SafetyVerdict(
            decision=SafetyDecision.REFUSE,
            reason="I'm concerned for you.",
            resources=["Helpline 111"],
        )

    res = anyio.run(Agent(FileStorage(tmp_path), _BoomLLM(), safety=refuse).run, "harmful thing")
    assert res.safety == SafetyDecision.REFUSE
    assert res.tools_called == []
    assert "concerned" in res.reply
    assert "Helpline 111" in res.reply


def test_agent_warn_injects_note(tmp_path):
    def warn(_message):
        return SafetyVerdict(decision=SafetyDecision.WARN, reason="Mind the traffic.")

    llm = _CapturingLLM()
    res = anyio.run(Agent(FileStorage(tmp_path), llm, safety=warn).run, "clean roadside litter")
    assert res.safety == SafetyDecision.WARN
    assert res.reply == "ok"
    system_msgs = [m["content"] for m in llm.messages if m.get("role") == "system"]
    assert any("Mind the traffic." in s for s in system_msgs)
