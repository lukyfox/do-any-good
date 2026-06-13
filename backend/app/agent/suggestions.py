"""Goody suggestion generation (daily + weekly) with self/other balance.

The model returns structured suggestions (json_schema); we enforce the spec rule
that a weekly plan contains at least one Goody for the user themselves, then
persist the plan as planned Goodies.
"""
from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

from pydantic import BaseModel, ValidationError

from ..llm_client import LLMClient
from ..storage import FileStorage, Goody, GoodyCategory, GoodyStatus, UserProfile
from .prompts import SYSTEM_PROMPT, profile_context


class GoodySuggestion(BaseModel):
    """A proposed deed (content only — no date/status/id yet)."""

    title: str
    description: str | None = None
    category: GoodyCategory = GoodyCategory.OTHERS
    why: str | None = None
    how: str | None = None
    bonus: str | None = None


DEFAULT_SELF_GOODY = GoodySuggestion(
    title="A moment for yourself",
    description=(
        "Do one small kind thing for yourself — a short walk, rest, a favourite tea, "
        "or a few quiet minutes."
    ),
    category=GoodyCategory.SELF,
    why="Caring for yourself is also a good deed.",
)

_SUGGESTION_PROPS = {
    "title": {"type": "string"},
    "description": {"type": "string"},
    "category": {"type": "string", "enum": ["self", "others"]},
    "why": {"type": "string"},
    "how": {"type": "string"},
    "bonus": {"type": "string"},
}
_SUGGESTION_OBJECT = {
    "type": "object",
    "properties": _SUGGESTION_PROPS,
    "required": ["title", "category"],
}

DAILY_SCHEMA = {"name": "goody_suggestion", "strict": False, "schema": _SUGGESTION_OBJECT}
WEEKLY_SCHEMA = {
    "name": "weekly_plan",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {"suggestions": {"type": "array", "items": _SUGGESTION_OBJECT}},
        "required": ["suggestions"],
    },
}


def _suggestion_messages(profile: UserProfile | None, instruction: str) -> list[dict]:
    system = "\n\n".join([SYSTEM_PROMPT, profile_context(profile), instruction])
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "Please suggest now."},
    ]


def _parse_suggestion(raw: object) -> GoodySuggestion | None:
    if not isinstance(raw, dict):
        return None
    try:
        return GoodySuggestion.model_validate(raw)
    except ValidationError:
        return None


def suggest_daily(llm: LLMClient, profile: UserProfile | None) -> GoodySuggestion:
    instruction = (
        "Suggest exactly one good deed (Goody) for the user's next day, personalized to their "
        "profile. Provide the structured fields."
    )
    result = llm.complete(_suggestion_messages(profile, instruction), response_schema=DAILY_SCHEMA)
    return _parse_suggestion(result.parsed) or DEFAULT_SELF_GOODY


def suggest_weekly(llm: LLMClient, profile: UserProfile | None) -> list[GoodySuggestion]:
    instruction = (
        "Create a 7-day plan of good deeds, one per day, personalized to the profile. Include "
        "at least one Goody for the user themselves (category 'self'). Return them under "
        "'suggestions'."
    )
    result = llm.complete(_suggestion_messages(profile, instruction), response_schema=WEEKLY_SCHEMA)
    items: list[GoodySuggestion] = []
    if isinstance(result.parsed, dict):
        for raw in result.parsed.get("suggestions", []):
            parsed = _parse_suggestion(raw)
            if parsed:
                items.append(parsed)
    return ensure_self_balance(items)


def ensure_self_balance(suggestions: list[GoodySuggestion]) -> list[GoodySuggestion]:
    """Guarantee at least one self-directed Goody, preserving the plan length."""
    if any(s.category == GoodyCategory.SELF for s in suggestions):
        return suggestions
    if not suggestions:
        return [DEFAULT_SELF_GOODY]
    return [*suggestions[:-1], DEFAULT_SELF_GOODY]


def _to_goody(suggestion: GoodySuggestion, on: date_cls) -> Goody:
    return Goody(
        date=on,
        title=suggestion.title,
        description=suggestion.description,
        category=suggestion.category,
        why=suggestion.why,
        how=suggestion.how,
        bonus=suggestion.bonus,
        status=GoodyStatus.PLANNED,
    )


def persist_one(storage: FileStorage, suggestion: GoodySuggestion, on: date_cls) -> Goody:
    return storage.add_goody(_to_goody(suggestion, on))


def persist_plan(
    storage: FileStorage, suggestions: list[GoodySuggestion], start: date_cls
) -> list[Goody]:
    return [persist_one(storage, s, start + timedelta(days=i)) for i, s in enumerate(suggestions)]
