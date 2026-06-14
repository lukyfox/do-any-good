"""Pydantic models for stored entities (profile, Goody, journal)."""
from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GoodyCategory(str, Enum):
    """Whether a deed is primarily for others or for the user themselves."""

    SELF = "self"
    OTHERS = "others"


class GoodyStatus(str, Enum):
    PLANNED = "planned"
    DONE = "done"
    MISSED = "missed"


class GoodyNotFoundError(Exception):
    """Raised when a Goody id is not present in the store."""


class UserProfile(BaseModel):
    """A user's profile. Locality, age and social environment are optional and
    may be refused by the user without affecting operation."""

    nickname: str
    email: str | None = None
    locality: str | None = None
    age: int | None = None
    social_environment: str | None = None
    preferences: list[str] = Field(default_factory=list)
    notes: str | None = None
    version: int = 1
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Goody(BaseModel):
    """A single good deed — planned or carried out."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    date: date_cls
    title: str
    description: str | None = None
    category: GoodyCategory
    status: GoodyStatus = GoodyStatus.PLANNED
    why: str | None = None
    how: str | None = None
    bonus: str | None = None
    link: str | None = None
    user_summary: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class JournalEntry(BaseModel):
    """A free-form diary entry, optionally tied to a Goody."""

    timestamp: datetime = Field(default_factory=_now)
    title: str | None = None
    text: str
    goody_id: str | None = None
