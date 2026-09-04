"""Single source of truth for where the vault lives.

Every helper and both MCP servers used to hardcode the iCloud Drive path.
That is still the default, so nothing changes on this Mac -- but a host
that has no iCloud (a serverless function serving Claude on iOS, working
from a git clone of the vault) can point at its own copy by setting
SECOND_BRAIN_VAULT.
"""
import os
from pathlib import Path

DEFAULT_VAULT = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "iCloud~md~obsidian"
    / "Documents"
    / "MyVault"
)

VAULT = Path(os.environ.get("SECOND_BRAIN_VAULT") or DEFAULT_VAULT).expanduser().resolve()
