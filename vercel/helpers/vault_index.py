#!/usr/bin/env python3
"""Print a compact structured map of the whole vault: every note's path,
hub, tags, and one-line description, grouped under its project/topic hub.

Usage: vault_index.py [--archive] [--hub <hub-id>]

This is the vault's primary DISCOVERY mechanism. The curated tier (session
summaries, hubs, notes, Inbox) is ~2k tokens, so it fits in one call and
lets the reader do semantic matching directly -- pick the right note by
meaning, then read_note it. That strictly beats guessing keywords at
search_notes.py, which is literal matching and silently misses a note
whose wording differs from the query (measured: 3 of 4 natural phrasings
of a real question returned nothing, while the note was obvious from this
index).

The archive tier (Claude Archive/Bulk export/, ~250 historical
conversations) is opt-in via --archive and much thinner per note -- those
files have no `## Topic` section, so their description is just the title.
Full-text search remains the better tool for the archive tier.
"""
import argparse
import re
from pathlib import Path

from vault_paths import VAULT  # honors $SECOND_BRAIN_VAULT; defaults to the iCloud vault
EXCLUDED_DIR_NAMES = {".obsidian", ".claude-code", ".drafts", ".git"}
ARCHIVE_PREFIX = "Claude Archive/Bulk export"

FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
ID_RE = re.compile(r"^id:\s*(\S+)", re.MULTILINE)
TYPE_RE = re.compile(r"^type:\s*(project|topic)\s*$", re.MULTILINE)
TITLE_RE = re.compile(r'^title:\s*"([^"]+)"', re.MULTILINE)
HUB_FIELD_RE = re.compile(r"^(?:topic|project):\s*(\S+)", re.MULTILINE)
TAGS_RE = re.compile(r"^tags:\s*\[(.*?)\]", re.MULTILINE)
TOPIC_SECTION_RE = re.compile(r"^##\s+Topic\s*\n+(.+)$", re.MULTILINE)
H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# Tags that carry no discovery signal: export markers, the tag that every
# session has, hub self-markers, and anything of the form topic/x or
# project/x (already shown as the note's hub, so repeating it is noise).
NOISE_TAGS = {
    "claude-archive", "bulk-export", "claude-session",
    "project-hub", "topic-hub", "archive-dashboard",
}

# Descriptions are for picking the right note, not for reading its content
# -- a few summaries run 500+ chars, which crowds the index without
# changing which file you'd choose. read_note has the full text.
MAX_DESC = 240


def iter_vault_md_files():
    for p in VAULT.rglob("*.md"):
        rel_parts = p.relative_to(VAULT).parts
        if any(part in EXCLUDED_DIR_NAMES or part.startswith(".") for part in rel_parts[:-1]):
            continue
        # Templates/ holds unfilled scaffolding ({{title}} placeholders) and
        # Index.md files are folder stubs -- neither is findable content.
        if rel_parts[0] == "Templates" or p.stem == "Index":
            continue
        yield p


def clean_inline(text):
    """Strip wikilink syntax so descriptions read as prose."""
    return WIKILINK_RE.sub(r"\1", text).strip()


def truncate(text, limit=MAX_DESC):
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def parse_note(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    fm_match = FM_RE.match(text)
    frontmatter = fm_match.group(1) if fm_match else ""
    body = text[fm_match.end():] if fm_match else text

    id_match = ID_RE.search(frontmatter)
    type_match = TYPE_RE.search(frontmatter)
    is_hub = bool(id_match and type_match)

    tags = []
    tags_match = TAGS_RE.search(frontmatter)
    if tags_match:
        for raw in tags_match.group(1).split(","):
            tag = raw.strip().strip("'\"")
            if tag and "/" not in tag and tag not in NOISE_TAGS and not tag.endswith("-capture"):
                tags.append(tag)

    # Description: a session's `## Topic` line is the curated one-liner;
    # otherwise fall back to the H1, then the filename.
    desc = ""
    topic_match = TOPIC_SECTION_RE.search(body)
    if topic_match:
        desc = topic_match.group(1)
    if not desc:
        h1_match = H1_RE.search(body)
        if h1_match:
            desc = h1_match.group(1)
    desc = truncate(clean_inline(desc) or path.stem)

    if is_hub:
        title_match = TITLE_RE.search(frontmatter)
        # A hub's description is its first prose paragraph, not its H1
        # (which just repeats the title).
        hub_desc = ""
        h1_match = H1_RE.search(body)
        if h1_match:
            for line in body[h1_match.end():].splitlines():
                if line.startswith("#"):
                    break
                if line.strip():
                    hub_desc = truncate(clean_inline(line))
                    break
        return {
            "path": path,
            "is_hub": True,
            "id": id_match.group(1),
            "type": type_match.group(1),
            "name": title_match.group(1) if title_match else path.stem,
            "desc": hub_desc,
        }

    hub_match = HUB_FIELD_RE.search(frontmatter)
    return {
        "path": path,
        "is_hub": False,
        "hub": hub_match.group(1) if hub_match else None,
        "tags": tags,
        "desc": desc,
    }


def main(argv=None):
    out: list[str] = []

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", action="store_true",
                    help="Also include Claude Archive/Bulk export/ (~250 historical conversations, title-only descriptions)")
    ap.add_argument("--hub", help="Show only this hub id and its notes")
    args = ap.parse_args(argv)

    hubs = {}
    notes = []
    for path in iter_vault_md_files():
        rel = str(path.relative_to(VAULT))
        if not args.archive and rel.startswith(ARCHIVE_PREFIX):
            continue
        parsed = parse_note(path)
        if parsed is None:
            continue
        if parsed["is_hub"]:
            hubs[parsed["id"]] = parsed
        else:
            parsed["archived"] = rel.startswith(ARCHIVE_PREFIX)
            notes.append(parsed)

    if args.hub:
        if args.hub not in hubs:
            out.append(f"No hub with id \"{args.hub}\". Run without --hub to see all hubs.")
            return "\n".join(out)
        hubs = {args.hub: hubs[args.hub]}
        notes = [n for n in notes if n["hub"] == args.hub]

    by_hub = {hub_id: [] for hub_id in hubs}
    unfiled = []
    for note in notes:
        if note["hub"] in by_hub:
            by_hub[note["hub"]].append(note)
        else:
            unfiled.append(note)

    tier = "curated + archive" if args.archive else "curated"
    hub_word = "hub" if len(hubs) == 1 else "hubs"
    out.append(f"# Vault index — {len(notes)} notes across {len(hubs)} {hub_word} (tier: {tier})")
    if not args.archive:
        out.append(f"# Archive tier omitted (Claude Archive/Bulk export/, ~250 historical "
              f"conversations). Pass --archive / include_archive=True for the full vault.")
    out.append("# Paths are vault-relative — pass one straight to read_note.")

    order = sorted(hubs.values(), key=lambda h: (h["type"] != "project", h["name"]))
    for hub in order:
        hub_notes = sorted(by_hub[hub["id"]], key=lambda n: str(n["path"]), reverse=True)
        n_arch = sum(1 for n in hub_notes if n["archived"])
        counts = f"{len(hub_notes) - n_arch} curated"
        if n_arch:
            counts += f", {n_arch} archived"
        out.append(f"\n## {hub['name']}  (`{hub['id']}`, {hub['type']}, {counts})")
        out.append(f"{hub['path'].relative_to(VAULT)}")
        if hub["desc"]:
            out.append(f"  {hub['desc']}")
        if not hub_notes:
            out.append("  (no notes filed under this hub yet)")
        for note in hub_notes:
            tag_str = f" [{','.join(note['tags'])}]" if note["tags"] else ""
            out.append(f"  - {note['path'].relative_to(VAULT)}{tag_str} — {note['desc']}")

    if unfiled:
        out.append(f"\n## Unfiled ({len(unfiled)} notes with no project/topic hub)")
        for note in sorted(unfiled, key=lambda n: str(n["path"]), reverse=True):
            tag_str = f" [{','.join(note['tags'])}]" if note["tags"] else ""
            out.append(f"  - {note['path'].relative_to(VAULT)}{tag_str} — {note['desc']}")

    return "\n".join(out)

if __name__ == "__main__":
    print(main())
