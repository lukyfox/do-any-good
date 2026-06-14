"""MCP server exposing the Do Any Good storage layer as tools.

Run as a stdio MCP server:  python -m backend.app.mcp_server.server
The backend agent (M4) connects to this server as an MCP host.
"""
from __future__ import annotations

from datetime import date as date_cls
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..config import get_settings
from ..storage import (
    FileStorage,
    Goody,
    GoodyCategory,
    GoodyNotFoundError,
    GoodyStatus,
    JournalEntry,
    UserProfile,
)


def build_mcp(storage: FileStorage) -> FastMCP:
    """Build a FastMCP server whose tools operate on the given storage."""
    mcp = FastMCP("do-any-good")

    @mcp.tool()
    def get_profile() -> dict[str, Any]:
        """Return the current user profile as {"profile": <profile|null>}."""
        profile = storage.load_profile()
        return {"profile": profile.model_dump(mode="json") if profile else None}

    @mcp.tool()
    def upsert_profile(
        nickname: str,
        email: str | None = None,
        locality: str | None = None,
        age: int | None = None,
        social_environment: str | None = None,
        preferences: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Create or update the profile (saves a new version each call). Locality,
        age and social environment are optional and may be omitted."""
        profile = UserProfile(
            nickname=nickname,
            email=email,
            locality=locality,
            age=age,
            social_environment=social_environment,
            preferences=preferences or [],
            notes=notes,
        )
        return storage.save_profile(profile).model_dump(mode="json")

    @mcp.tool()
    def add_goody(
        date: str,
        title: str,
        category: str,
        description: str | None = None,
        why: str | None = None,
        how: str | None = None,
        bonus: str | None = None,
        link: str | None = None,
    ) -> dict[str, Any]:
        """Add a planned Goody. `date` is ISO (YYYY-MM-DD) — today or a future day;
        `category` is 'self' or 'others'. Pass `link` with a relevant URL (e.g. a
        campaign or organization page) when the deed references one."""
        goody = Goody(
            date=date_cls.fromisoformat(date),
            title=title,
            category=GoodyCategory(category),
            description=description,
            why=why,
            how=how,
            bonus=bonus,
            link=link,
        )
        return storage.add_goody(goody).model_dump(mode="json")

    @mcp.tool()
    def list_goodies(
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """List Goodies as {"goodies": [...]}, optionally filtered by status
        ('planned'|'done'|'missed') and an inclusive ISO date range."""
        goodies = storage.list_goodies(
            status=GoodyStatus(status) if status else None,
            date_from=date_cls.fromisoformat(date_from) if date_from else None,
            date_to=date_cls.fromisoformat(date_to) if date_to else None,
        )
        return {"goodies": [g.model_dump(mode="json") for g in goodies]}

    @mcp.tool()
    def set_goody_status(
        goody_id: str, status: str, summary: str | None = None
    ) -> dict[str, Any]:
        """Mark a Goody 'done' or 'missed', optionally storing the user's summary."""
        try:
            updated = storage.set_goody_status(goody_id, GoodyStatus(status), summary)
        except GoodyNotFoundError as err:
            raise ValueError(f"Goody not found: {err}") from err
        return updated.model_dump(mode="json")

    @mcp.tool()
    def delete_goody(goody_id: str) -> dict[str, Any]:
        """Permanently delete a Goody by id (use for unwanted entries)."""
        try:
            storage.delete_goody(goody_id)
        except GoodyNotFoundError as err:
            raise ValueError(f"Goody not found: {err}") from err
        return {"deleted": goody_id}

    @mcp.tool()
    def append_journal(
        text: str, title: str | None = None, goody_id: str | None = None
    ) -> dict[str, Any]:
        """Append a free-form journal entry, optionally linked to a Goody id."""
        entry = JournalEntry(text=text, title=title, goody_id=goody_id)
        return storage.append_journal(entry).model_dump(mode="json")

    return mcp


def main() -> None:
    """Entry point: run the MCP server over stdio using configured storage."""
    storage = FileStorage(get_settings().data_dir)
    build_mcp(storage).run()


if __name__ == "__main__":
    main()
