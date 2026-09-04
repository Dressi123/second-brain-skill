#!/usr/bin/env python3
"""Print current project and topic IDs by scanning the vault.

This is the source of truth — never trust hardcoded ID lists elsewhere.
"""
import re
import sys
from pathlib import Path

from vault_paths import VAULT  # honors $SECOND_BRAIN_VAULT; defaults to the iCloud vault


def discover(folder: Path):
    """Return list of (id, display_name) tuples for hub notes in folder."""
    items = []
    if not folder.exists():
        return items
    for p in sorted(folder.glob("*.md")):
        if p.stem in ("Index",):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:1500]
        except OSError:
            continue
        m_id = re.search(r"^id:\s*(\S+)", text, re.M)
        m_title = re.search(r'^title:\s*"([^"]+)"', text, re.M)
        if m_id:
            items.append((m_id.group(1), m_title.group(1) if m_title else p.stem))
    return items


def main(argv=None):
    out: list[str] = []

    projects = discover(VAULT / "Projects")
    topics = discover(VAULT / "Notes" / "Topics")

    out.append("# Vault taxonomy (live, scanned just now)")
    out.append("")
    out.append(f"## Projects ({len(projects)})")
    if not projects:
        out.append("_(none)_")
    for hub_id, name in projects:
        out.append(f"- `{hub_id}` → {name}")
    out.append("")
    out.append(f"## Topics ({len(topics)})")
    if not topics:
        out.append("_(none)_")
    for hub_id, name in topics:
        out.append(f"- `{hub_id}` → {name}")
    out.append("")
    out.append(f"_Vault: {VAULT}_")

    return "\n".join(out)

if __name__ == "__main__":
    print(main())
