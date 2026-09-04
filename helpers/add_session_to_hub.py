#!/usr/bin/env python3
"""Append a backlink from a hub note to a session summary, under '## Sessions'.

Usage: add_session_to_hub.py --hub <path to hub note> --session <basename, no .md> --date YYYY-MM-DD --summary "one-line description"

Idempotent: if the session's basename already appears anywhere in the hub
file, does nothing (prevents duplicate entries on reruns).

Keeps the hub note itself as a living index of curated session summaries,
which is the graph edge that hand-written sessions otherwise never get
(they link to the hub, but nothing links back).
"""
import argparse
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hub", required=True, help="Path to the hub note (Projects/*.md or Notes/Topics/*.md)")
    ap.add_argument("--session", required=True, help="Session file basename, without .md")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--summary", required=True, help="One-line description of the session")
    args = ap.parse_args()

    hub_path = Path(args.hub)
    if not hub_path.is_file():
        print(f"error: hub not found: {hub_path}", file=sys.stderr)
        sys.exit(1)

    text = hub_path.read_text(encoding="utf-8")

    if args.session in text:
        print(f"skip: {args.session} already referenced in {hub_path.name}")
        return

    entry = f"- {args.date} — [[{args.session}]] — {args.summary}\n"
    lines = text.splitlines(keepends=True)

    # Find an existing '## Sessions' heading.
    sessions_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Sessions":
            sessions_idx = i
            break

    if sessions_idx is not None:
        # Insert as the first bullet right after the heading (+ blank line, if present).
        insert_at = sessions_idx + 1
        if insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1
        lines.insert(insert_at, entry)
    else:
        # No Sessions section yet: create one, right before the first other
        # '## ' heading, or at end of file if there isn't one.
        first_heading_idx = None
        for i, line in enumerate(lines):
            if line.startswith("## "):
                first_heading_idx = i
                break
        new_section = ["## Sessions\n", "\n", entry, "\n"]
        if first_heading_idx is not None:
            lines[first_heading_idx:first_heading_idx] = new_section
        else:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append("\n")
            lines.extend(new_section)

    hub_path.write_text("".join(lines), encoding="utf-8")
    print(f"linked: {args.session} -> {hub_path.name}")


if __name__ == "__main__":
    main()
