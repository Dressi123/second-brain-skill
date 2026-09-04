#!/usr/bin/env python3
"""Create a new project or topic hub note in the vault.

Usage:
  new_hub.py --type project --id travel-app --name "Travel App" --description "..."
  new_hub.py --type topic   --id cooking   --name "Cooking"     --description "..."

Validates kebab-case ID and that the ID isn't already in use.
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from vault_paths import VAULT  # honors $SECOND_BRAIN_VAULT; defaults to the iCloud vault


def main():
    parser = argparse.ArgumentParser(description="Create a new project or topic hub.")
    parser.add_argument("--type", required=True, choices=["project", "topic"])
    parser.add_argument("--id", required=True, help="Short kebab-case ID (e.g. cooking-app)")
    parser.add_argument("--name", required=True, help='Display name (e.g. "Cooking App")')
    parser.add_argument("--description", required=True, help="One-paragraph description")
    args = parser.parse_args()

    if not re.match(r"^[a-z][a-z0-9-]*$", args.id):
        print(f"ERROR: id must be lowercase kebab-case (got: {args.id!r})")
        sys.exit(1)

    folder = VAULT / "Projects" if args.type == "project" else VAULT / "Notes" / "Topics"
    folder.mkdir(parents=True, exist_ok=True)

    hub_path = folder / f"{args.name}.md"
    if hub_path.exists():
        print(f"ERROR: file already exists: {hub_path}")
        sys.exit(1)

    # Check id collision against other hubs of same type
    for p in folder.glob("*.md"):
        if p.stem == "Index":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")[:1500]
        m = re.search(r"^id:\s*(\S+)", text, re.M)
        if m and m.group(1) == args.id:
            print(f"ERROR: id {args.id!r} is already used by {p.name}")
            sys.exit(1)

    content = f"""---
title: "{args.name}"
type: {args.type}
id: {args.id}
tags: [{args.type}-hub, {args.type}/{args.id}]
created: {datetime.now().date()}
---

# {args.name}

{args.description}

## Status

_(fill in: where are we right now? what's the current focus?)_

## Conversations (0)

_No conversations yet. Sessions tagged with `{args.type}: {args.id}` will accumulate here over time.
End meaningful sessions by writing a summary to `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault/Claude Archive/Sessions/`
that includes the wikilink `[[{args.name}]]` in the body — that creates the graph edge._
"""

    hub_path.write_text(content, encoding="utf-8")
    print(f"✓ Created hub: {hub_path}")
    print(f"  type: {args.type}")
    print(f"  id:   {args.id}")
    print(f"  tag:  #{args.type}/{args.id}")
    print()
    print("To link a session summary to this hub, include in the body:")
    print(f"  [[{args.name}]]")


if __name__ == "__main__":
    main()
