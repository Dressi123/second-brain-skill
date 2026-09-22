#!/usr/bin/env python3
"""Validate a session summary or a triaged capture.

Usage: validate.py [--mode session|capture] <path-to-note.md>

Two kinds of note live in this vault and they carry their hub edge in
opposite directions, so one set of checks cannot serve both.

A **session summary** owns its edge: the body carries an explicit
`[[Hub Name]]` wikilink pointing at the hub.

A **capture** is the other way round. Captures arrive from Desktop/iOS
already written and are filed by triage, which links them FROM the hub's
`## Captures` section. Nothing is added to the capture's body, so demanding
a forward wikilink flags every correctly-filed capture in the vault. The
real invariant is the back-link, and that is what capture mode checks.

Mode is auto-detected from content -- a `source:` key or a
`claude-<surface>-capture` tag means a capture -- and falls back to session
mode when neither is present. `--mode` overrides.

Checks, both modes:
- Has YAML frontmatter, and `date: YYYY-MM-DD`
- Has either `project: <id>` or `topic: <id>` matching a real hub
- Has `tags: [...]` including project/<id> or topic/<id>

Session mode only:
- `claude-session` tag
- Body contains an explicit [[Hub Name]] wikilink

Capture mode only:
- A `claude-<surface>-capture` tag
- The hub note links back to this file from its `## Captures` section
  (skipped for a capture still in `Inbox/`, which is pending triage, not broken)
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


CAPTURE_TAG_RE = re.compile(r"claude-[a-z0-9]+-capture")


def detect_mode(fm: str) -> str:
    """Session or capture, decided from frontmatter alone.

    Both signals are written by the capture tooling, not by hand, and both
    survive the file being moved out of Inbox/ during triage. Absent either,
    assume session: that is the mode the SessionEnd hook relies on, and it
    greps this output for "ERRORS:" to decide whether to delete a summary,
    so an ambiguous file must not silently change branch.
    """
    if re.search(r"^source:\s*\S+", fm, re.M):
        return "capture"
    if CAPTURE_TAG_RE.search(fm):
        return "capture"
    return "session"


def hub_path_for(hub_name: str) -> Path | None:
    """Locate a hub note by display name, project or topic."""
    for folder in (VAULT / "Projects", VAULT / "Notes" / "Topics"):
        candidate = folder / f"{hub_name}.md"
        if candidate.exists():
            return candidate
    return None


def hub_links_back(hub_name: str, stem: str) -> bool | None:
    """Does the hub note link to this capture?

    Returns None when the hub note itself cannot be found, so the caller can
    tell "hub does not link back" from "could not check".
    """
    hub = hub_path_for(hub_name)
    if hub is None:
        return None
    text = hub.read_text(encoding="utf-8", errors="replace")
    # Accept [[stem]] and [[stem|alias]], matching the forward-link check.
    return bool(re.search(rf"\[\[{re.escape(stem)}(\||\]\])", text))


def main():
    args = [a for a in sys.argv[1:]]
    mode_override = None
    if "--mode" in args:
        i = args.index("--mode")
        if i + 1 >= len(args) or args[i + 1] not in ("session", "capture"):
            print("Usage: validate.py [--mode session|capture] <path-to-note.md>")
            sys.exit(2)
        mode_override = args[i + 1]
        del args[i:i + 2]

    if not args:
        print("Usage: validate.py [--mode session|capture] <path-to-note.md>")
        sys.exit(2)

    path = Path(args[0]).expanduser()
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        sys.exit(2)

    text = path.read_text(encoding="utf-8")
    errors = []
    warnings = []
    notes = []
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

            mode = mode_override or detect_mode(fm)

            m_tags = re.search(r"^tags:\s*\[([^\]]+)\]", fm, re.M)
            if not m_tags:
                if mode == "capture":
                    warnings.append("No tags array found (recommend `tags: [claude-desktop-capture, topic/<id>]`)")
                else:
                    warnings.append("No tags array found (recommend `tags: [claude-session, project/<id>]`)")
            else:
                tags_str = m_tags.group(1)
                if mode == "capture":
                    if not CAPTURE_TAG_RE.search(tags_str):
                        warnings.append(
                            "Missing a `claude-<surface>-capture` tag "
                            "(e.g. `claude-desktop-capture`, `claude-remote-capture`)"
                        )
                elif "claude-session" not in tags_str:
                    warnings.append("Missing `claude-session` tag")
                expected_tag = None
                if m_proj:
                    expected_tag = f"project/{m_proj.group(1)}"
                elif m_topic:
                    expected_tag = f"topic/{m_topic.group(1)}"
                if expected_tag and expected_tag not in tags_str:
                    warnings.append(f"Missing `{expected_tag}` tag")

            if hub_name_expected and mode == "session":
                # Accept either [[Name]] or [[Name|alias]]
                pat = re.escape(hub_name_expected)
                if not re.search(rf"\[\[{pat}(\||\]\])", body):
                    errors.append(
                        f"Body missing required wikilink to hub: `[[{hub_name_expected}]]` "
                        f"(creates the graph edge that clusters this summary)"
                    )
            elif hub_name_expected and mode == "capture":
                # A capture in Inbox/ has not been triaged yet, so no hub links
                # to it and none should. Pending is a normal state, not a fault.
                if path.parent.name == "Inbox":
                    notes.append(
                        "Pending triage in `Inbox/` -- hub back-link not expected yet"
                    )
                else:
                    linked = hub_links_back(hub_name_expected, path.stem)
                    if linked is None:
                        warnings.append(
                            f"Could not find hub note `{hub_name_expected}.md` to check its back-link"
                        )
                    elif not linked:
                        errors.append(
                            f"Hub `[[{hub_name_expected}]]` does not link back to this capture "
                            f"(add it under that hub's `## Captures` section -- a capture's body "
                            f"carries no wikilink, so the hub's link is the only graph edge)"
                        )

    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  ! {w}")
    if notes:
        print("NOTES:")
        for n in notes:
            print(f"  · {n}")
    if not errors and not warnings:
        print("✓ Validation passed")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
