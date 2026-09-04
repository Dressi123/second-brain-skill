#!/usr/bin/env python3
"""Validate a session summary file's frontmatter and hub wikilink.

Usage: validate.py <path-to-session-summary.md>

Checks:
- Has YAML frontmatter
- Has `date: YYYY-MM-DD`
- Has either `project: <id>` or `topic: <id>` matching a real hub
- Has `tags: [...]` including claude-session and project/<id> or topic/<id>
- Body contains an explicit [[Hub Name]] wikilink
"""
import re
import sys
from pathlib import Path

from vault_paths import VAULT  # honors $SECOND_BRAIN_VAULT; defaults to the iCloud vault


def discover_ids(folder: Path):
    """Return dict of {id: display_name} for hub notes in folder."""
    ids = {}
    if not folder.exists():
        return ids
    for p in folder.glob("*.md"):
        if p.stem == "Index":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")[:1500]
        m_id = re.search(r"^id:\s*(\S+)", text, re.M)
        m_title = re.search(r'^title:\s*"([^"]+)"', text, re.M)
        if m_id:
            ids[m_id.group(1)] = m_title.group(1) if m_title else p.stem
    return ids


def main():
    if len(sys.argv) < 2:
        print("Usage: validate.py <path-to-session-summary.md>")
        sys.exit(2)

    path = Path(sys.argv[1]).expanduser()
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        sys.exit(2)

    text = path.read_text(encoding="utf-8")
    errors = []
    warnings = []
    hub_name_expected = None

    if not text.startswith("---\n"):
        errors.append("Missing YAML frontmatter (must start with ---)")
    else:
        end = text.find("\n---\n", 4)
        if end < 0:
            errors.append("Frontmatter not closed (missing closing ---)")
        else:
            fm = text[4:end]
            body = text[end + 5:]

            if not re.search(r"^date:\s*\d{4}-\d{2}-\d{2}", fm, re.M):
                errors.append("Missing or malformed `date: YYYY-MM-DD`")

            m_proj = re.search(r"^project:\s*(\S+)", fm, re.M)
            m_topic = re.search(r"^topic:\s*(\S+)", fm, re.M)
            if not m_proj and not m_topic:
                errors.append("Need either `project: <id>` or `topic: <id>` in frontmatter")

            project_ids = discover_ids(VAULT / "Projects")
            topic_ids = discover_ids(VAULT / "Notes" / "Topics")

            if m_proj:
                pid = m_proj.group(1)
                if pid in project_ids:
                    hub_name_expected = project_ids[pid]
                else:
                    errors.append(
                        f"`project: {pid}` doesn't match any hub. "
                        f"Known projects: {sorted(project_ids.keys())}"
                    )
            if m_topic:
                tid = m_topic.group(1)
                if tid in topic_ids:
                    hub_name_expected = topic_ids[tid]
                else:
                    errors.append(
                        f"`topic: {tid}` doesn't match any hub. "
                        f"Known topics: {sorted(topic_ids.keys())}"
                    )

            m_tags = re.search(r"^tags:\s*\[([^\]]+)\]", fm, re.M)
            if not m_tags:
                warnings.append("No tags array found (recommend `tags: [claude-session, project/<id>]`)")
            else:
                tags_str = m_tags.group(1)
                if "claude-session" not in tags_str:
                    warnings.append("Missing `claude-session` tag")
                expected_tag = None
                if m_proj:
                    expected_tag = f"project/{m_proj.group(1)}"
                elif m_topic:
                    expected_tag = f"topic/{m_topic.group(1)}"
                if expected_tag and expected_tag not in tags_str:
                    warnings.append(f"Missing `{expected_tag}` tag")

            if hub_name_expected:
                # Accept either [[Name]] or [[Name|alias]]
                pat = re.escape(hub_name_expected)
                if not re.search(rf"\[\[{pat}(\||\]\])", body):
                    errors.append(
                        f"Body missing required wikilink to hub: `[[{hub_name_expected}]]` "
                        f"(creates the graph edge that clusters this summary)"
                    )

    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  ! {w}")
    if not errors and not warnings:
        print("✓ Validation passed")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
