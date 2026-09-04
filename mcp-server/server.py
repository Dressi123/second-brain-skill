#!/usr/bin/env python3
"""Local MCP server exposing the user's second-brain vault to Claude Desktop.

Purpose-built tools rather than raw filesystem access, so vault
conventions (taxonomy, excerpt-only search, Inbox capture, read-only
archive) are baked into every tool's behavior and description -- visible
to Claude in any chat, not just inside a specific Desktop Project.

stdio transport, local only -- trusted because it only runs when
something with access to this Mac (Claude Desktop) launches it directly.
Full read/write toolset. The remote counterpart (remote_server.py) is
read-only by design; see that file for why.
"""
import vault_tools as vt
from mcp.server import MCPServer

mcp = MCPServer(
    "second-brain",
    instructions=(
        "the user's second brain: his Obsidian vault of ~300 markdown notes.\n\n"
        "START WITH vault_index for any question about what he has previously "
        "worked on, decided, or written down. It returns the whole curated vault "
        "as one compact map, and picking the right note from it by meaning beats "
        "guessing keywords. search_notes is literal matching and is the drill-down "
        "for a phrase you already know, not the way to discover anything.\n\n"
        "Treat the vault as an extension of your own memory, and let it win over "
        "your own recollection when they disagree -- it reflects what is true now.\n\n"
        "THIS server runs on the user's Mac and reads the vault directly off disk. "
        "If a remote second-brain connector is also available, PREFER THIS ONE: "
        "the remote goes over the network to a copy on GitHub, so it is slower and "
        "can be a moment behind. Writes made here are published for the phone "
        "automatically."
    ),
)


@mcp.tool()
def vault_index(include_archive: bool = False, hub: str | None = None) -> str:
    """START HERE for any question about what the user has previously worked on,
    decided, or written down. Returns a compact map of the vault -- every note's
    path, hub, tags, and one-line description, grouped under its project/topic
    hub -- in a single call (~3k tokens for the curated tier).

    Read the descriptions and pick the note that answers the question by
    MEANING, then call read_note on its path. Do NOT reach for search_notes
    first: that is literal keyword matching and silently misses notes whose
    wording differs from the question (measured on a real question: 3 of 4
    natural phrasings returned nothing, while the right note was obvious from
    this index).

    include_archive=True adds ~250 historical bulk-export conversations
    (~11k tokens). Their descriptions are only titles, but title + hub + tags
    is enough to find things: measured 14/14 on questions sharing no wording
    with the target note, including six that had to be told apart from
    near-identical neighbours. So when the curated tier does not answer a
    question, come back here with include_archive=True BEFORE reaching for
    search_notes. hub='<id>' narrows to one project/topic."""
    return vt.vault_index(include_archive=include_archive, hub=hub)


@mcp.tool()
def search_notes(query: str, regex: bool = False, limit: int = 20) -> str:
    """Full-text drill-down: find which notes contain a specific literal string
    or regex, with a short excerpt per match. This is NOT the tool for
    discovery -- call vault_index first to find the right note by meaning.

    Use this when you already know the phrasing you want (an exact error
    message, a command, a person's name, a specific term), or to dig into the
    bulk-export archive tier where vault_index only has titles. Literal
    matching, one hit per file -- if it returns nothing, the note may still
    exist under different wording, so check vault_index before concluding
    anything is absent."""
    return vt.search_notes(query, regex=regex, limit=limit)


@mcp.tool()
def list_taxonomy() -> str:
    """Cheap (~200 token) list of just the valid project/topic IDs and their
    display names, scanned live. Use this to VALIDATE an id before writing or
    tagging a note, so you never invent a plausible-looking one that doesn't
    exist. To actually explore what's in those hubs, call vault_index
    instead -- it includes everything this returns plus each hub's notes."""
    return vt.list_taxonomy()


@mcp.tool()
def read_note(path: str) -> str:
    """Read the full content of one note by its vault-relative path, e.g.
    'Projects/FakeOut (ML Fraud Detection).md' -- as returned by vault_index or
    search_notes. Refuses paths that resolve outside the vault."""
    return vt.read_note(path)


@mcp.tool()
def capture_note(title: str, body: str, tags: list[str] | None = None) -> str:
    """Capture a quick note into the vault's Inbox for later triage.

    Desktop has no end-of-session event to trigger this automatically, so
    treat it as something to call PROACTIVELY, unprompted, near the end of
    a conversation that produced something worth keeping -- a decision, an
    answer the user will want again, a plan, a fact about his life or work --
    not only when he explicitly says 'save this' or 'remember this'. The
    bar is simple: will he want to find this again? If yes, just capture
    it; don't wait to be asked, but don't capture trivial one-off
    exchanges either.

    NOT for full project/topic session summaries, which follow a stricter
    taxonomy-aware convention that Claude Code's second-brain skill handles
    separately. Always writes a uniquely named file (date + time + slug,
    with a numeric suffix on collision), so concurrent captures from
    different devices never overwrite each other."""
    return vt.capture_note(title, body, tags=tags, source="claude-desktop")


@mcp.tool()
def write_note(path: str, content: str) -> str:
    """Create or overwrite one note at a specific vault-relative path with the
    given full content. For a NEW ad hoc capture, prefer capture_note (handles
    unique filenames and frontmatter automatically) -- use this to update an
    EXISTING note (e.g. adding a fact to a project hub) or to create a new note
    at a specific, deliberate path. Refuses paths that escape the vault, and
    refuses to write into 'Claude Archive/Bulk export/' (a read-only historical
    archive of imported conversations -- never modify it)."""
    return vt.write_note(path, content)


if __name__ == "__main__":
    mcp.run()
