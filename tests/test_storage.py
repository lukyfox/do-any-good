from datetime import date

import pytest

from backend.app.storage import (
    FileStorage,
    Goody,
    GoodyCategory,
    GoodyNotFoundError,
    GoodyStatus,
    JournalEntry,
    UserProfile,
)


def test_profile_roundtrip(tmp_path):
    store = FileStorage(tmp_path)
    assert store.load_profile() is None
    saved = store.save_profile(
        UserProfile(nickname="Aleš", locality="Brno", preferences=["help elderly"])
    )
    assert saved.version == 1
    loaded = store.load_profile()
    assert loaded is not None
    assert loaded.nickname == "Aleš"
    assert loaded.locality == "Brno"
    assert loaded.preferences == ["help elderly"]


def test_profile_versioning(tmp_path):
    store = FileStorage(tmp_path)
    v1 = store.save_profile(UserProfile(nickname="Aleš"))
    v2 = store.save_profile(UserProfile(nickname="Aleš", age=30))
    assert (v1.version, v2.version) == (1, 2)
    assert v2.created_at == v1.created_at  # created_at preserved across versions
    assert v2.updated_at >= v1.updated_at
    assert [p.version for p in store.profile_history()] == [1, 2]
    assert store.load_profile_version(1).age is None
    assert store.load_profile_version(2).age == 30
    assert store.load_profile().version == 2


def test_optional_profile_fields_skippable(tmp_path):
    store = FileStorage(tmp_path)
    saved = store.save_profile(UserProfile(nickname="anon"))
    assert saved.email is None
    assert saved.locality is None
    assert saved.age is None


def test_goody_add_get_list(tmp_path):
    store = FileStorage(tmp_path)
    g = store.add_goody(
        Goody(date=date(2026, 6, 13), title="Call grandma", category=GoodyCategory.OTHERS)
    )
    assert store.get_goody(g.id).title == "Call grandma"
    assert store.get_goody("missing") is None
    assert len(store.list_goodies()) == 1


def test_goody_status_filter_and_date_range(tmp_path):
    store = FileStorage(tmp_path)
    store.add_goody(Goody(date=date(2026, 6, 10), title="A", category=GoodyCategory.SELF))
    b = store.add_goody(Goody(date=date(2026, 6, 12), title="B", category=GoodyCategory.OTHERS))
    store.add_goody(Goody(date=date(2026, 6, 15), title="C", category=GoodyCategory.SELF))
    store.set_goody_status(b.id, GoodyStatus.DONE, summary="went well")

    done = store.list_goodies(status=GoodyStatus.DONE)
    assert [g.title for g in done] == ["B"]
    assert done[0].user_summary == "went well"

    in_range = store.list_goodies(date_from=date(2026, 6, 11), date_to=date(2026, 6, 13))
    assert [g.title for g in in_range] == ["B"]

    planned = store.list_goodies(status=GoodyStatus.PLANNED)
    assert {g.title for g in planned} == {"A", "C"}


def test_set_status_missing_raises(tmp_path):
    store = FileStorage(tmp_path)
    with pytest.raises(GoodyNotFoundError):
        store.set_goody_status("nope", GoodyStatus.DONE)


def test_set_status_transition_persists(tmp_path):
    store = FileStorage(tmp_path)
    g = store.add_goody(Goody(date=date(2026, 6, 13), title="walk", category=GoodyCategory.SELF))
    assert g.status == GoodyStatus.PLANNED
    updated = store.set_goody_status(g.id, GoodyStatus.MISSED)
    assert updated.status == GoodyStatus.MISSED
    assert store.get_goody(g.id).status == GoodyStatus.MISSED


def test_journal_append_and_read(tmp_path):
    store = FileStorage(tmp_path)
    assert store.read_journal() == ""
    store.append_journal(JournalEntry(title="Den první", text="Pomohl jsem sousedovi."))
    store.append_journal(JournalEntry(title="Day two", text="Took a walk."))
    content = store.read_journal()
    assert "Pomohl jsem sousedovi." in content
    assert content.index("Den první") < content.index("Day two")  # append order preserved


def test_delete_goody(tmp_path):
    store = FileStorage(tmp_path)
    g = store.add_goody(Goody(date=date(2026, 6, 13), title="X", category=GoodyCategory.SELF))
    store.delete_goody(g.id)
    assert store.list_goodies() == []


def test_delete_goody_missing_raises(tmp_path):
    store = FileStorage(tmp_path)
    with pytest.raises(GoodyNotFoundError):
        store.delete_goody("nope")
