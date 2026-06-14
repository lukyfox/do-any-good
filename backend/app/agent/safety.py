"""Safety gate for the Do Any Good agent.

Before planning deeds, the agent classifies the user's message. Harmful intent
or signs of crisis (self-harm, abuse, dependence) -> 'refuse' with a
compassionate message and professional-help resources; risky-but-okay -> 'warn';
otherwise 'allow'. This complements the safety instructions in the system prompt
(defense in depth).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, ValidationError

from ..llm_client import LLMClient


class SafetyDecision(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    REFUSE = "refuse"


class SafetyVerdict(BaseModel):
    decision: SafetyDecision = SafetyDecision.ALLOW
    reason: str = ""
    resources: list[str] = Field(default_factory=list)


SAFETY_PROMPT = (
    "You are a safety classifier for a 'good deed' assistant. Given the user's message, "
    "decide whether it is safe to help plan a good deed.\n"
    "- 'refuse': the message shows intent to harm someone (including the user), or signs of "
    "crisis (self-harm, suicidal thoughts, abuse, severe substance dependence). Give a "
    "compassionate reason and relevant professional-help resources.\n"
    "- 'warn': broadly fine, but the deed could carry a notable risk to the user or others; "
    "give a brief caution as the reason.\n"
    "- 'allow': a normal, safe request.\n"
    "Use the structured schema only."
)

SAFETY_SCHEMA = {
    "name": "safety_verdict",
    "schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["allow", "warn", "refuse"]},
            "reason": {"type": "string"},
            "resources": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["decision", "reason", "resources"],
        "additionalProperties": False,
    },
    "strict": True,
}


def classify_safety(llm: LLMClient, message: str) -> SafetyVerdict:
    """Classify a user message into a safety verdict.

    Fails open (ALLOW) on parse errors; the system prompt is the second layer.
    """
    result = llm.complete(
        [
            {"role": "system", "content": SAFETY_PROMPT},
            {"role": "user", "content": message},
        ],
        response_schema=SAFETY_SCHEMA,
    )
    if isinstance(result.parsed, dict):
        try:
            return SafetyVerdict.model_validate(result.parsed)
        except ValidationError:
            pass
    return SafetyVerdict()


class LLMSafetyChecker:
    """Callable safety checker backed by an LLM."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def __call__(self, message: str) -> SafetyVerdict:
        return classify_safety(self._llm, message)


def refusal_message(verdict: SafetyVerdict) -> str:
    """Compose a compassionate refusal, appending any help resources."""
    reason = verdict.reason or (
        "I'm sorry, but I can't help with that — your safety and the safety of others "
        "come first."
    )
    lines = [reason]
    if verdict.resources:
        lines += ["", "Here are some resources that may help:"]
        lines += [f"- {r}" for r in verdict.resources]
    return "\n".join(lines)
