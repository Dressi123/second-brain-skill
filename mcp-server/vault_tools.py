"""Shared vault operations, used by server.py (local stdio, full
read/write toolset, Claude Desktop) and, as a vendored copy, by
vercel/app.py (hosted, Claude iOS/web).

Plain functions here, not @mcp.tool()-decorated -- each server module
registers whichever subset it exposes under its own MCPServer instance.
"""
import os
import re
import subprocess
import sys
from datetime import datetime
from importlib import import_module
from pathlib import Path

HELPERS = Path(
    os.environ.get("SECOND_BRAIN_HELPERS")
    or Path.home() / ".claude" / "skills" / "second-brain" / "helpers"
).expanduser().resolve()

# The helpers own the vault-path decision (see helpers/vault_paths.py), so
# there is exactly one place that honors $SECOND_BRAIN_VAULT.
if str(HELPERS) not in sys.path:
    sys.path.insert(0, str(HELPERS))
from vault_paths import VAULT  # noqa: E402


def _run_helper(script: str, *args: str) -> str:
    """Call a helper's main() in this process and return what it produces.

    This used to shell out to `python3 <script>`, which a serverless host
    has no way to spawn -- that subprocess was the one thing tying these
    tools to a real machine. Each helper's main() returns its report as a
    string (its __main__ block prints that), so nothing here touches
    stdout: two tool calls running concurrently on the async server cannot
    capture each other's output the way a redirected global stdout would.
    """
    module = import_module(script.removesuffix(".py"))
    try:
        return module.main(list(args)).strip()
    except SystemExit as exc:  # argparse exits on a bad argument
        return f"Helper {script} rejected its arguments: {exc.code}"


# -- git sync (Mac-local only) ------------------------------------------
#
# On this Mac the vault is a git working tree whose mirror on GitHub is what
# Claude on the iPhone reads. So a read here pulls first and a write here
# pushes after, and the two views never drift.
#
# A host with no local clone -- the serverless server, which talks to the
# GitHub API directly and is always current by construction -- has neither
# the sync script nor the git dir, so both calls below become no-ops with
# no configuration. That absence IS the switch.

SYNC_SCRIPT = HELPERS / "vault_git_sync.sh"
GIT_DIR = Path.home() / ".second-brain-git"


def _sync(direction: str) -> None:
    """Best effort: syncing must never be the reason a vault tool fails."""
    if not (SYNC_SCRIPT.is_file() and GIT_DIR.is_dir()):
        return
    try:
        subprocess.run(
            ["bash", str(SYNC_SCRIPT), direction],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _resolve_in_vault(rel_path: str) -> Path | None:
    """Resolve a vault-relative path, refusing anything that escapes the vault."""
    target = (VAULT / rel_path).resolve()
    try:
        target.relative_to(VAULT)
    except ValueError:
        return None
    return target


def vault_index(include_archive: bool = False, hub: str | None = None) -> str:
    _sync("pull")
    args = []
    if include_archive:
        args.append("--archive")
    if hub:
        args += ["--hub", hub]
    return _run_helper("vault_index.py", *args)


def search_notes(query: str, regex: bool = False, limit: int = 20) -> str:
    _sync("pull")
    args = [query]
    if regex:
        args.append("--regex")
    args += ["--limit", str(limit)]
    return _run_helper("search_notes.py", *args)


def list_taxonomy() -> str:
    _sync("pull")
    return _run_helper("list_taxonomy.py")


def read_note(path: str) -> str:
    _sync("pull")
    target = _resolve_in_vault(path)
    if target is None:
        return "Error: path escapes the vault, refusing to read."
    if not target.is_file():
        return f"Error: no such file: {path}"
    return target.read_text(encoding="utf-8", errors="replace")


def render_capture(
    title: str,
    body: str,
    tags: list[str] | None = None,
    source: str = "claude-desktop",
    taken: set[str] | None = None,
) -> tuple[str, str]:
    """Build one Inbox capture: its vault-relative path and its full content.

    Shared, rather than duplicated, because two hosts create captures now --
    this Mac writing to iCloud, and the serverless server committing straight
    to GitHub. A capture made on the phone should be indistinguishable from
    one made here, so the naming and frontmatter live in exactly one place.

    `taken` lets a caller that cannot cheaply stat the vault (the serverless
    one) supply the names it already knows about.
    """
    now = datetime.now()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "note"
    base = f"{now.strftime('%Y-%m-%d-%H%M')}-{slug}"

    def is_free(name: str) -> bool:
        if taken is not None and name in taken:
            return False
        return not (VAULT / "Inbox" / name).exists()

    name = f"{base}.md"
    suffix = 2
    while not is_free(name):
        name = f"{base}-{suffix}.md"
        suffix += 1

    tag_line = ", ".join([f"{source}-capture"] + (tags or []))
    content = (
        f"---\n"
        f"date: {now.strftime('%Y-%m-%d')}\n"
        f"tags: [{tag_line}]\n"
        f"source: {source}\n"
        f"---\n\n"
        f"# {title}\n\n{body}\n"
    )
    return f"Inbox/{name}", content


def check_write_path(path: str) -> str | None:
    """Return an error message if this path may not be written, else None.

    Shared with the serverless server, which enforces the same two rules
    without ever touching a local filesystem.
    """
    if _resolve_in_vault(path) is None:
        return "Error: path escapes the vault, refusing to write."
    if "Bulk export" in Path(path).parts:
        return "Error: Claude Archive/Bulk export/ is a read-only historical archive, refusing to write."
    return None


def capture_note(title: str, body: str, tags: list[str] | None = None, source: str = "claude-desktop") -> str:
    rel, content = render_capture(title, body, tags=tags, source=source)
    target = VAULT / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _sync("push")
    return f"Saved to {rel}"


def write_note(path: str, content: str) -> str:
    problem = check_write_path(path)
    if problem:
        return problem
    target = _resolve_in_vault(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _sync("push")
    return f"Wrote {path}"
