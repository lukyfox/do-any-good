from datetime import date

from fastapi.testclient import TestClient

from backend.app.main import app, get_rag, get_storage
from backend.app.overview import build_overview
from backend.app.storage import FileStorage, Goody, GoodyCategory, GoodyStatus, UserProfile


def _seed(storage):
    storage.add_goody(Goody(date=date(2026, 6, 10), title="A", category=GoodyCategory.OTHERS))
    b = storage.add_goody(Goody(date=date(2026, 6, 11), title="B", category=GoodyCategory.SELF))
    storage.add_goody(Goody(date=date(2026, 6, 12), title="C", category=GoodyCategory.OTHERS))
    storage.set_goody_status(b.id, GoodyStatus.DONE, summary="nice")
    return b


def _client(storage):
    app.dependency_overrides[get_storage] = lambda: storage
    return TestClient(app)


def test_build_overview(tmp_path):
    storage = FileStorage(tmp_path)
    _seed(storage)
    overview = build_overview(storage)
    assert overview["counts"] == {
        "total": 3,
        "planned": 2,
        "done": 1,
        "missed": 0,
        "self": 1,
        "others": 2,
    }
    assert [g["title"] for g in overview["done"]] == ["B"]


def test_get_goodies_endpoint(tmp_path):
    storage = FileStorage(tmp_path)
    _seed(storage)
    try:
        client = _client(storage)
        assert len(client.get("/goodies").json()["goodies"]) == 3
        done = client.get("/goodies", params={"status": "done"}).json()["goodies"]
        assert [g["title"] for g in done] == ["B"]
    finally:
        app.dependency_overrides.clear()


def test_update_status_endpoint(tmp_path):
    storage = FileStorage(tmp_path)
    g = storage.add_goody(Goody(date=date(2026, 6, 13), title="walk", category=GoodyCategory.SELF))
    try:
        client = _client(storage)
        r = client.post(f"/goodies/{g.id}/status", json={"status": "done", "summary": "felt good"})
        assert r.status_code == 200
        assert r.json()["status"] == "done"
        assert r.json()["user_summary"] == "felt good"
        assert storage.get_goody(g.id).status == GoodyStatus.DONE  # persisted
    finally:
        app.dependency_overrides.clear()


def test_update_status_404(tmp_path):
    storage = FileStorage(tmp_path)
    try:
        client = _client(storage)
        assert client.post("/goodies/nope/status", json={"status": "done"}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_overview_endpoint(tmp_path):
    storage = FileStorage(tmp_path)
    _seed(storage)
    try:
        overview = _client(storage).get("/overview").json()
        assert overview["counts"]["total"] == 3
        assert overview["counts"]["done"] == 1
    finally:
        app.dependency_overrides.clear()


def test_journal_endpoints(tmp_path):
    storage = FileStorage(tmp_path)
    try:
        client = _client(storage)
        client.post("/journal", json={"text": "Pomohl jsem sousedovi.", "title": "Den 1"})
        markdown = client.get("/journal").json()["markdown"]
        assert "Pomohl jsem sousedovi." in markdown
        assert "Den 1" in markdown
    finally:
        app.dependency_overrides.clear()


def test_delete_goody_endpoint(tmp_path):
    storage = FileStorage(tmp_path)
    g = storage.add_goody(Goody(date=date(2026, 6, 13), title="X", category=GoodyCategory.SELF))
    try:
        client = _client(storage)
        assert client.delete(f"/goodies/{g.id}").status_code == 200
        assert storage.get_goody(g.id) is None
        assert client.delete("/goodies/nope").status_code == 404
    finally:
        app.dependency_overrides.clear()


class _FakeRag:
    def __init__(self):
        self.saved = []

    def save(self, profile, goody):
        self.saved.append((profile, goody))

    def find_match(self, profile):
        return None


def test_mark_done_saves_to_rag(tmp_path):
    storage = FileStorage(tmp_path)
    storage.save_profile(UserProfile(nickname="Aleš", preferences=["x"]))
    g = storage.add_goody(Goody(date=date(2026, 6, 13), title="X", category=GoodyCategory.SELF))
    rag = _FakeRag()
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_rag] = lambda: rag
    try:
        r = TestClient(app).post(f"/goodies/{g.id}/status", json={"status": "done"})
        assert r.status_code == 200
        assert [saved[1].id for saved in rag.saved] == [g.id]
    finally:
        app.dependency_overrides.clear()


def test_mark_missed_does_not_save_to_rag(tmp_path):
    storage = FileStorage(tmp_path)
    storage.save_profile(UserProfile(nickname="Aleš"))
    g = storage.add_goody(Goody(date=date(2026, 6, 13), title="X", category=GoodyCategory.SELF))
    rag = _FakeRag()
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_rag] = lambda: rag
    try:
        TestClient(app).post(f"/goodies/{g.id}/status", json={"status": "missed"})
        assert rag.saved == []
    finally:
        app.dependency_overrides.clear()
