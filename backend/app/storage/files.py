"""File-based storage for profiles, Goodies, and the journal.

Layout under the storage root:

    profile/current.md       canonical profile (JSON frontmatter + readable body)
    profile/history/v{N}.md  one snapshot per saved version
    goodies.jsonl            one Goody per line (queryable log)
    journal.md               appended Markdown entries

The profile frontmatter is JSON (a strict subset of YAML) so it round-trips
losslessly through pydantic without a YAML dependency or type-coercion surprises.
"""
from __future__ import annotations

import json
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .models import Goody, GoodyNotFoundError, GoodyStatus, JournalEntry, UserProfile

_FENCE = "---"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FileStorage:
    """Markdown/JSONL storage rooted at a single user's data directory."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.profile_dir = self.root / "profile"
        self.profile_history_dir = self.profile_dir / "history"
        self.profile_path = self.profile_dir / "current.md"
        self.goodies_path = self.root / "goodies.jsonl"
        self.journal_path = self.root / "journal.md"

    # -- frontmatter helpers ---------------------------------------------

    @staticmethod
    def _read_frontmatter(text: str) -> dict:
        lines = text.splitlines()
        if not lines or lines[0].strip() != _FENCE:
            raise ValueError("missing frontmatter fence")
        for i in range(1, len(lines)):
            if lines[i].strip() == _FENCE:
                return json.loads("\n".join(lines[1:i]))
        raise ValueError("unterminated frontmatter")

    @staticmethod
    def _render_profile(profile: UserProfile) -> str:
        front = json.dumps(profile.model_dump(mode="json"), indent=2, ensure_ascii=False)
        body = [f"# Profile: {profile.nickname} (v{profile.version})", ""]
        if profile.notes:
            body += ["## Notes", profile.notes, ""]
        if profile.preferences:
            body.append("## Preferences")
            body += [f"- {p}" for p in profile.preferences]
            body.append("")
        return f"{_FENCE}\n{front}\n{_FENCE}\n\n" + "\n".join(body)

    # -- profile ----------------------------------------------------------

    def _load_profile_file(self, path: Path) -> UserProfile | None:
        """Read one profile file, tolerating a missing, empty, or corrupt file."""
        if not path.exists():
            return None
        try:
            return UserProfile.model_validate(
                self._read_frontmatter(path.read_text(encoding="utf-8"))
            )
        except (ValueError, ValidationError):
            return None

    def load_profile(self) -> UserProfile | None:
        current = self._load_profile_file(self.profile_path)
        if current is not None:
            return current
        # current.md missing or corrupt (e.g. truncated by an interrupted write):
        # fall back to the latest saved version.
        history = self.profile_history()
        return history[-1] if history else None

    def save_profile(self, profile: UserProfile) -> UserProfile:
        existing = self.load_profile()
        if existing is None:
            version, created_at = 1, profile.created_at
        else:
            version, created_at = existing.version + 1, existing.created_at
        stored = profile.model_copy(
            update={"version": version, "created_at": created_at, "updated_at": _now()}
        )
        self.profile_history_dir.mkdir(parents=True, exist_ok=True)
        rendered = self._render_profile(stored)
        self.profile_path.write_text(rendered, encoding="utf-8")
        (self.profile_history_dir / f"v{version}.md").write_text(rendered, encoding="utf-8")
        return stored

    def profile_history(self) -> list[UserProfile]:
        if not self.profile_history_dir.exists():
            return []
        profiles = [
            profile
            for path in self.profile_history_dir.glob("v*.md")
            if (profile := self._load_profile_file(path)) is not None
        ]
        return sorted(profiles, key=lambda p: p.version)

    def load_profile_version(self, version: int) -> UserProfile | None:
        return self._load_profile_file(self.profile_history_dir / f"v{version}.md")

    # -- goodies ----------------------------------------------------------

    def _read_goodies(self) -> list[Goody]:
        if not self.goodies_path.exists():
            return []
        goodies = []
        for line in self.goodies_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                goodies.append(Goody.model_validate_json(stripped))
        return goodies

    def _write_goodies(self, goodies: list[Goody]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        body = "".join(g.model_dump_json() + "\n" for g in goodies)
        self.goodies_path.write_text(body, encoding="utf-8")

    def add_goody(self, goody: Goody) -> Goody:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.goodies_path.open("a", encoding="utf-8") as f:
            f.write(goody.model_dump_json() + "\n")
        return goody

    def get_goody(self, goody_id: str) -> Goody | None:
        return next((g for g in self._read_goodies() if g.id == goody_id), None)

    def list_goodies(
        self,
        status: GoodyStatus | None = None,
        date_from: date_cls | None = None,
        date_to: date_cls | None = None,
    ) -> list[Goody]:
        result = [
            g
            for g in self._read_goodies()
            if (status is None or g.status == status)
            and (date_from is None or g.date >= date_from)
            and (date_to is None or g.date <= date_to)
        ]
        return sorted(result, key=lambda g: (g.date, g.created_at))

    def set_goody_status(
        self, goody_id: str, status: GoodyStatus, summary: str | None = None
    ) -> Goody:
        goodies = self._read_goodies()
        for i, g in enumerate(goodies):
            if g.id == goody_id:
                goodies[i] = g.model_copy(
                    update={
                        "status": status,
                        "user_summary": summary if summary is not None else g.user_summary,
                        "updated_at": _now(),
                    }
                )
                self._write_goodies(goodies)
                return goodies[i]
        raise GoodyNotFoundError(goody_id)

    def delete_goody(self, goody_id: str) -> None:
        goodies = self._read_goodies()
        remaining = [g for g in goodies if g.id != goody_id]
        if len(remaining) == len(goodies):
            raise GoodyNotFoundError(goody_id)
        self._write_goodies(remaining)

    # -- journal ----------------------------------------------------------

    def append_journal(self, entry: JournalEntry) -> JournalEntry:
        self.root.mkdir(parents=True, exist_ok=True)
        header = entry.timestamp.isoformat()
        if entry.title:
            header = f"{header} — {entry.title}"
        block = f"## {header}\n\n{entry.text}\n"
        if entry.goody_id:
            block += f"\n_Goody: {entry.goody_id}_\n"
        with self.journal_path.open("a", encoding="utf-8") as f:
            f.write(block + "\n")
        return entry

    def read_journal(self) -> str:
        if not self.journal_path.exists():
            return ""
        return self.journal_path.read_text(encoding="utf-8")
