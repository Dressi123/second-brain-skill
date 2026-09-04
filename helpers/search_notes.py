#!/usr/bin/env python3
"""Full-text drill-down: which notes contain a literal string or regex.

Usage: search_notes.py <query> [--regex] [--limit N] [--context N]

NOT the discovery tool -- vault_index.py is. Use this when you already
know the exact phrasing you want (an error message, a command, a name, a
specific term), or to dig into the ~250 bulk-export archive notes, where
vault_index.py only has titles.

Searches every .md file in the vault and returns, per matching file: its
vault-relative path, the nearest preceding markdown heading, and a short
excerpt. Never whole files -- Read the specific path once you've narrowed
it down. One hit per file, so this is an index into candidates, not a
line-by-line dump.

An empty result does not mean absent: literal matching misses any note
whose wording differs from the query (measured on a real question, 3 of 4
natural phrasings returned nothing while the right note was obvious from
vault_index.py). Always check the index before concluding something isn't
in the vault.
"""
import argparse
import re
import sys
from pathlib import Path

from vault_paths import VAULT  # honors $SECOND_BRAIN_VAULT; defaults to the iCloud vault
EXCLUDED_DIR_NAMES = {".obsidian", ".claude-code", ".drafts", ".git"}


def iter_vault_md_files():
    for p in VAULT.rglob("*.md"):
        parts = p.relative_to(VAULT).parts[:-1]
        if any(part in EXCLUDED_DIR_NAMES or part.startswith(".") for part in parts):
            continue
        yield p


def nearest_heading(lines, match_idx):
    for i in range(match_idx, -1, -1):
        line = lines[i].strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None


def main(argv=None):
    out: list[str] = []

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query")
    ap.add_argument("--regex", action="store_true", help="Treat query as a regex instead of a literal substring")
    ap.add_argument("--limit", type=int, default=20, help="Max number of matching files to show (default 20)")
    ap.add_argument("--context", type=int, default=80, help="Max excerpt length in characters (default 80)")
    args = ap.parse_args(argv)

    pattern = re.compile(args.query if args.regex else re.escape(args.query), re.IGNORECASE)

    results = []
    for path in iter_vault_md_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = pattern.search(line)
            if not m:
                continue
            heading = nearest_heading(lines, i)
            excerpt = line.strip()
            if len(excerpt) > args.context:
                start = max(0, m.start() - args.context // 2)
                prefix = "..." if start > 0 else ""
                excerpt = prefix + excerpt[start:start + args.context] + "..."
            results.append((str(path.relative_to(VAULT)), heading, excerpt))
            break  # one hit per file -- this is an index, not a grep dump

    if not results:
        out.append(f"No text match for: {args.query}")
        out.append("Note: this is literal matching -- the note may still exist under "
              "different wording. Run vault_index.py before concluding it isn't "
              "in the vault.")
        return "\n".join(out)

    out.append(f"# {len(results)} file(s) containing \"{args.query}\" (showing up to {args.limit})\n")
    for rel, heading, excerpt in results[: args.limit]:
        heading_str = f' -- under "{heading}"' if heading else ""
        out.append(f"- `{rel}`{heading_str}: {excerpt}")
    if len(results) > args.limit:
        out.append(f"\n...and {len(results) - args.limit} more file(s). Narrow the query or raise --limit.")

    return "\n".join(out)

if __name__ == "__main__":
    print(main())
