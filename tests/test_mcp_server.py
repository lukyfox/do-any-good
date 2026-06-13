import json

import anyio
from mcp.shared.memory import create_connected_server_and_client_session as connected

from backend.app.mcp_server import build_mcp
from backend.app.storage import FileStorage

TOOL_NAMES = {
    "get_profile",
    "upsert_profile",
    "add_goody",
    "list_goodies",
    "set_goody_status",
    "append_journal",
}


def _json(result):
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


def test_tools_exposed(tmp_path):
    async def scenario():
        async with connected(build_mcp(FileStorage(tmp_path))) as s:
            tools = await s.list_tools()
            assert {t.name for t in tools.tools} == TOOL_NAMES

    anyio.run(scenario)


def test_get_profile_empty(tmp_path):
    async def scenario():
        async with connected(build_mcp(FileStorage(tmp_path))) as s:
            assert _json(await s.call_tool("get_profile", {}))["profile"] is None

    anyio.run(scenario)


def test_upsert_and_get_profile(tmp_path):
    storage = FileStorage(tmp_path)

    async def scenario():
        async with connected(build_mcp(storage)) as s:
            created = _json(
                await s.call_tool("upsert_profile", {"nickname": "Aleš", "locality": "Brno"})
            )
            assert created["nickname"] == "Aleš"
            got = _json(await s.call_tool("get_profile", {}))
            assert got["profile"]["locality"] == "Brno"

    anyio.run(scenario)
    assert storage.load_profile().nickname == "Aleš"  # mutated on disk


def test_add_and_list_goodies(tmp_path):
    storage = FileStorage(tmp_path)

    async def scenario():
        async with connected(build_mcp(storage)) as s:
            added = _json(
                await s.call_tool(
                    "add_goody",
                    {"date": "2026-06-14", "title": "Call grandma", "category": "others"},
                )
            )
            assert added["category"] == "others"
            listed = _json(await s.call_tool("list_goodies", {}))
            assert [g["title"] for g in listed["goodies"]] == ["Call grandma"]

    anyio.run(scenario)
    assert len(storage.list_goodies()) == 1  # mutated on disk


def test_set_status_and_filter(tmp_path):
    storage = FileStorage(tmp_path)

    async def scenario():
        async with connected(build_mcp(storage)) as s:
            a = _json(
                await s.call_tool(
                    "add_goody", {"date": "2026-06-10", "title": "A", "category": "self"}
                )
            )
            await s.call_tool(
                "add_goody", {"date": "2026-06-12", "title": "B", "category": "others"}
            )
            done = _json(
                await s.call_tool(
                    "set_goody_status",
                    {"goody_id": a["id"], "status": "done", "summary": "great"},
                )
            )
            assert done["status"] == "done"
            assert done["user_summary"] == "great"
            res = _json(await s.call_tool("list_goodies", {"status": "done"}))
            assert [g["title"] for g in res["goodies"]] == ["A"]

    anyio.run(scenario)


def test_set_status_missing_is_error(tmp_path):
    async def scenario():
        async with connected(build_mcp(FileStorage(tmp_path))) as s:
            res = await s.call_tool("set_goody_status", {"goody_id": "nope", "status": "done"})
            assert res.isError

    anyio.run(scenario)


def test_append_journal(tmp_path):
    storage = FileStorage(tmp_path)

    async def scenario():
        async with connected(build_mcp(storage)) as s:
            entry = _json(
                await s.call_tool(
                    "append_journal", {"text": "Pomohl jsem sousedovi.", "title": "Den 1"}
                )
            )
            assert entry["title"] == "Den 1"

    anyio.run(scenario)
    assert "Pomohl jsem sousedovi." in storage.read_journal()  # mutated on disk
