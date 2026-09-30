"""Exercise every tool the local server declares, over a real MCP session."""
import json
import os
import subprocess
import sys

import pytest
from mcp.client import Client

from conftest import REPO

import server

pytestmark = pytest.mark.anyio

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

EXPECTED = {
    "vault_index": dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    "search_notes": dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    "list_taxonomy": dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    "read_note": dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    "capture_note": dict(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    "write_note": dict(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
}


async def call(name: str, **args) -> str:
    async with Client(server.mcp) as client:
        result = await client.call_tool(name, args)
    assert not result.is_error, result
    return result.content[0].text


def wire_hints(tools) -> dict[str, dict]:
    return {
        t.name: t.annotations.model_dump(by_alias=True, include={"read_only_hint", "destructive_hint",
                                                                  "idempotent_hint", "open_world_hint"})
        for t in tools
    }


async def test_every_tool_declares_all_four_hints():
    async with Client(server.mcp) as client:
        tools = (await client.list_tools()).tools
    assert wire_hints(tools) == EXPECTED


def test_remote_server_declares_the_same_hints(vault):
    """vercel/app.py can't share a process with server.py (both import a
    module named vault_tools), so list its tools in a subprocess. Only the
    import and the listing run -- nothing that would reach GitHub."""
    script = (
        "import asyncio, json, app\n"
        "tools = asyncio.run(app.mcp.list_tools())\n"
        "print(json.dumps({t.name: t.annotations.model_dump(by_alias=True, exclude={'title'})"
        " for t in tools}))\n"
    )
    env = {**os.environ, "VAULT_REPO": "test/not-a-repo", "SECOND_BRAIN_VAULT": str(vault)}
    env.pop("SECOND_BRAIN_HELPERS")  # app.py points this at its own vendored copy
    out = subprocess.run([sys.executable, "-c", script], cwd=REPO / "vercel", env=env,
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == EXPECTED


async def test_vault_index_lists_hub_and_note():
    out = await call("vault_index")
    assert "test-project" in out


async def test_search_notes_finds_literal_match():
    out = await call("search_notes", query="flux capacitor")
    assert "Widget fix.md" in out


async def test_list_taxonomy_lists_hub():
    out = await call("list_taxonomy")
    assert "`test-project` → Test Project" in out


async def test_read_note_returns_content():
    out = await call("read_note", path="Notes/Widget fix.md")
    assert "new gasket" in out


async def test_read_note_refuses_path_outside_vault():
    out = await call("read_note", path="../outside.md")
    assert out.startswith("Error: path escapes the vault")


async def test_read_note_reports_missing_file():
    out = await call("read_note", path="Notes/nope.md")
    assert out == "Error: no such file: Notes/nope.md"


async def test_capture_note_writes_to_inbox(vault):
    out = await call("capture_note", title="Remember this", body="Some body.", tags=["idea"])
    rel = out.removeprefix("Saved to ")
    assert rel.startswith("Inbox/") and rel.endswith("-remember-this.md")
    text = (vault / rel).read_text()
    assert "tags: [claude-desktop-capture, idea]" in text
    assert "# Remember this\n\nSome body." in text


async def test_capture_note_never_overwrites(vault):
    first = await call("capture_note", title="Same", body="one")
    second = await call("capture_note", title="Same", body="two")
    assert first != second
    assert len(list((vault / "Inbox").glob("*.md"))) == 2


async def test_write_note_creates_and_overwrites(vault):
    assert await call("write_note", path="Notes/New.md", content="v1") == "Wrote Notes/New.md"
    await call("write_note", path="Notes/New.md", content="v2")
    assert (vault / "Notes" / "New.md").read_text() == "v2"


async def test_write_note_refuses_path_outside_vault(vault):
    out = await call("write_note", path="../escape.md", content="x")
    assert out.startswith("Error: path escapes the vault")
    assert not (vault.parent / "escape.md").exists()


async def test_write_note_refuses_bulk_export_archive(vault):
    out = await call("write_note", path="Claude Archive/Bulk export/old.md", content="x")
    assert "read-only historical archive" in out
    assert (vault / "Claude Archive" / "Bulk export" / "old.md").read_text() == "# Old\n"
