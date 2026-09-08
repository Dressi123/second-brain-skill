"""Single source of truth for where the vault lives.

Every helper and both MCP servers used to hardcode the iCloud Drive path,
which meant a clone carried its author's home directory and could not run
until someone rewrote it. Resolution order now:

1. $SECOND_BRAIN_VAULT -- a host with no iCloud (the serverless function
   serving Claude on iOS, working from a git clone of the vault) sets this.
2. .bootstrap.conf beside the skill -- written by bootstrap.sh and gitignored,
   so the tracked files stay generic and a set-up clone has a clean tree.
3. The default iCloud Obsidian location.

`python3 vault_paths.py` prints the resolved path, which is how the shell
hooks and SKILL.md refer to the vault without naming anyone's home directory.
"""
import os
import shlex
from pathlib import Path

DEFAULT_VAULT = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "iCloud~md~obsidian"
    / "Documents"
    / "MyVault"
)

CONF = Path(__file__).resolve().parent.parent / ".bootstrap.conf"


def _from_conf():
    """Read CONF_VAULT out of the shell-format config, if it is there."""
    try:
        for line in CONF.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "CONF_VAULT" and value.strip():
                # bootstrap.sh writes this with %q, so it may carry quoting.
                return shlex.split(value.strip())[0]
    except (OSError, ValueError):
        pass
    return None


VAULT = Path(
    os.environ.get("SECOND_BRAIN_VAULT") or _from_conf() or DEFAULT_VAULT
).expanduser().resolve()


if __name__ == "__main__":
    print(VAULT)
