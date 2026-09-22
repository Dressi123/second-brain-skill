#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["typesafe-sdk>=0.7.1"]
# ///
"""Propose (and optionally file) a hub for each Inbox capture, so the model
only has to look at the captures that are genuinely unclear.

Triage never rewrites a capture's body. Filing is three mechanical steps once
the hub is known: set `project:`/`topic:` in the frontmatter, add a line under
the hub's `## Captures`, and move the file to Notes/. Choosing the hub is the
only judgment, so that is all this decides:

  1. Jev picks one hub (or `none`) from every hub's name + description.
  2. Accepted only at confidence >= JEV_MIN_CONF. Scores vary a little between
     calls, so a capture near the threshold can land on either side.
  3. Anything else is left in Inbox/ for the model / Andreas to decide, exactly
     as SKILL.md's "triage inbox" says: never force a fit, never invent a hub.

Captures without a `source:` key (hand-made, not from capture_note) are never
auto-filed; validate.py can't tell them from session notes.

Runs under uv (dependencies declared above, cached after the first run), so
invoke it directly rather than with `python3`. Key: $TYPESAFE_API_KEY, else
the macOS keychain item "typesafe-api-key":
  security add-generic-password -a "$USER" -s typesafe-api-key -w

Usage:
  triage_inbox.py              # dry run: print a proposal per capture
  triage_inbox.py --apply      # file the confident ones, validate each
  triage_inbox.py --backtest   # score the rules against already-filed captures
"""
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from typesafe_sdk import Choice, TypeSafeClient  # noqa: E402
from vault_paths import VAULT  # noqa: E402

# Chosen with --backtest: Jev's wrong picks scored below it, its picks above it
# matched the hub the capture was filed under.
JEV_MIN_CONF = 0.8
BODY_CHARS = 6_000

FM_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


def load_hubs():
    """[(id, kind, name, description, path)] -- discovered live, like list_taxonomy."""
    hubs = []
    for kind, folder in (("project", VAULT / "Projects"), ("topic", VAULT / "Notes" / "Topics")):
        for p in sorted(folder.glob("*.md")):
            text = p.read_text(encoding="utf-8", errors="replace")
            fm = FM_RE.match(text)
            m_id = fm and re.search(r"^id:\s*(\S+)", fm.group(1), re.M)
            if not m_id:
                continue
            m_title = re.search(r'^title:\s*"([^"]+)"', fm.group(1), re.M)
            body = text[fm.end():]
            # First prose paragraph after the H1 is the hub's description.
            paras = [b.strip() for b in body.split("\n\n") if b.strip() and not b.strip().startswith("#")]
            hubs.append((m_id.group(1), kind, m_title.group(1) if m_title else p.stem,
                         paras[0][:400] if paras else "", p))
    return hubs


def parse(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = FM_RE.match(text)
    front = fm.group(1) if fm else ""
    body = text[fm.end():] if fm else text
    m = re.search(r"^tags:\s*\[(.*?)\]", front, re.M)
    tags = [t.strip().strip("'\"") for t in m.group(1).split(",")] if m else []
    m = re.search(r"^title:\s*(.+)$", front, re.M) or re.search(r"^#\s+(.+)$", body, re.M)
    title = m.group(1).strip().strip('"') if m else path.stem
    return {"path": path, "text": text, "front": front, "body": body, "tags": tags, "title": title,
            "has_source": bool(re.search(r"^source:", front, re.M))}


def api_key():
    """The SDK reads $TYPESAFE_API_KEY itself; the keychain fallback is ours."""
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", "typesafe-api-key", "-w"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def ask_jev(cap, hubs, client):
    criteria = {h[0]: f"{h[2]}: {h[3]}" for h in hubs}
    criteria["none"] = "Fits none of these hubs; a genuinely new subject."
    state = {"title": cap["title"], "tags": [t for t in cap["tags"] if not t.startswith("claude-")],
             "body": cap["body"][:BODY_CHARS]}
    response = client.system_one(state, {"hub": Choice(
        instructions="Which hub in a personal knowledge base should this captured note be filed under?",
        criteria=criteria,
    )})
    a = response.answers["hub"]
    return a.choice, a.confidence


def decide(cap, hubs, client, strip_hub_tags=False):
    """-> (hub_id | None, how, confidence)

    Tags are input to Jev, not a rule of their own: an incidental tag can name
    the wrong hub (a credit-card note tagged `motorcycle`)."""
    tags = cap["tags"]
    if strip_hub_tags:  # backtest: triage may have added topic/<id>; don't let it leak
        tags = [t for t in tags if not t.startswith(("topic/", "project/"))]
    if not client:
        return None, "no TypeSafe key", 0.0
    try:
        choice, conf = ask_jev(dict(cap, tags=tags), hubs, client)
    except Exception as e:
        return None, f"jev error: {e}", 0.0
    if choice == "none" or conf < JEV_MIN_CONF:
        return None, f"jev unsure ({choice} @ {conf:.2f})", conf
    return choice, f"jev {conf:.2f}", conf


def first_sentence(body):
    for para in body.split("\n\n"):
        p = para.strip()
        if p and not p.startswith(("#", "-", "|", ">", "```")):
            s = re.split(r"(?<=[.!?])\s", p, maxsplit=1)[0]
            return s if len(s) <= 220 else s[:217] + "..."
    return ""


def file_capture(cap, hub):
    hub_id, kind, _name, _desc, hub_path = hub
    src = cap["path"]
    dest = VAULT / "Notes" / src.name
    if dest.exists():
        raise RuntimeError(f"{dest.name} already exists in Notes/")

    # 1. frontmatter: exactly one of project:/topic:
    front = re.sub(r"^(project|topic):.*\n?", "", cap["front"] + "\n", flags=re.M).rstrip("\n")
    lines = front.split("\n")
    at = next((i + 1 for i, l in enumerate(lines) if l.startswith("date:")), 0)
    lines.insert(at, f"{kind}: {hub_id}")
    # ...and the matching `topic/<id>` tag validate.py expects on filed notes
    hub_tag = f"{kind}/{hub_id}"
    for i, l in enumerate(lines):
        m = re.match(r"^tags:\s*\[(.*)\]\s*$", l)
        if m and hub_tag not in [t.strip() for t in m.group(1).split(",")]:
            lines[i] = f"tags: [{m.group(1).strip()}, {hub_tag}]" if m.group(1).strip() else f"tags: [{hub_tag}]"
    if not any(l.startswith("tags:") for l in lines):
        lines.append(f"tags: [{hub_tag}]")
    new_text = "---\n" + "\n".join(lines) + "\n---\n" + cap["body"]

    # 2. hub back-link under ## Captures (created above the first other ## if missing)
    m = re.search(r"^date:\s*(\S+)", cap["front"], re.M)
    when = m.group(1) if m else date.today().isoformat()
    summary = first_sentence(cap["body"])
    entry = f"- {when} — [[{src.stem}|{cap['title']}]]" + (f" — {summary}" if summary else "")
    old_hub = hub_text = hub_path.read_text(encoding="utf-8")
    sec = re.search(r"^## Captures\s*\n", hub_text, re.M)
    if sec:
        nxt = re.search(r"^## ", hub_text[sec.end():], re.M)
        end = sec.end() + (nxt.start() if nxt else len(hub_text) - sec.end())
        block = hub_text[sec.end():end].rstrip("\n")
        hub_text = hub_text[:sec.end()] + (block + "\n" if block else "\n") + entry + "\n\n" + hub_text[end:].lstrip("\n")
    else:
        first = re.search(r"^## ", hub_text, re.M)
        insert = f"## Captures\n\n{entry}\n\n"
        hub_text = hub_text[:first.start()] + insert + hub_text[first.start():] if first else hub_text.rstrip("\n") + "\n\n" + insert

    # 3. write, move, validate -- roll everything back if validation fails
    hub_path.write_text(hub_text, encoding="utf-8")
    dest.write_text(new_text, encoding="utf-8")
    src.unlink()
    out = subprocess.run([sys.executable, str(HERE / "validate.py"), str(dest)], capture_output=True, text=True)
    if "ERRORS:" in out.stdout + out.stderr:
        src.write_text(cap["text"], encoding="utf-8")
        dest.unlink()
        hub_path.write_text(old_hub, encoding="utf-8")
        raise RuntimeError("validation failed, rolled back:\n" + (out.stdout + out.stderr).strip())


def backtest(hubs, client):
    kind_of = {h[0]: h[1] for h in hubs}
    rows = []
    for p in sorted((VAULT / "Notes").glob("20*.md")):
        cap = parse(p)
        m = re.search(r"^(project|topic):\s*(\S+)", cap["front"], re.M)
        if not (cap["has_source"] and m and m.group(2) in kind_of):
            continue
        truth = m.group(2)
        hub, how, conf = decide(cap, hubs, client, strip_hub_tags=True)
        rows.append((truth, hub, how, conf, p.name))
    print(f"{len(rows)} filed captures (hub tags like topic/<id> stripped to avoid leakage)\n")
    for label, sel in (("auto-filed", lambda r: r[1] is not None), ("left for review", lambda r: r[1] is None)):
        rs = [r for r in rows if sel(r)]
        right = sum(r[0] == r[1] for r in rs)
        print(f"  {label:<16} {len(rs):>3}" + (f"   correct {right}/{len(rs)}" if label != "left for review" else ""))
    print("\n  every capture, by Jev confidence:")
    for truth, hub, how, conf, name in sorted(rows, key=lambda r: -r[3]):
        mark = "   " if hub is None else ("ok " if hub == truth else "BAD")
        print(f"    {mark} {conf:.2f}  truth={truth:<20} {how[:60]:<60} {name[:40]}")


def main():
    key = api_key()
    if not key:
        print("(no TypeSafe key: nothing will be filed, every capture goes to review)")
        return run(load_hubs(), None)
    with TypeSafeClient(api_key=key) as client:  # retries 429/529 with backoff
        return run(load_hubs(), client)


def run(hubs, client):
    if "--backtest" in sys.argv:
        return backtest(hubs, client)
    apply = "--apply" in sys.argv
    by_id = {h[0]: h for h in hubs}
    report = {"filed": [], "proposed": [], "review": []}
    for p in sorted((VAULT / "Inbox").glob("*.md")):
        cap = parse(p)
        hub, how, _ = decide(cap, hubs, client)
        if hub and not cap["has_source"]:
            report["review"].append((p.name, f"would be {hub} ({how}), but no source: key"))
            continue
        if not hub:
            report["review"].append((p.name, how))
            continue
        if apply:
            try:
                file_capture(cap, by_id[hub])
                report["filed"].append((p.name, f"{hub} ({how})"))
            except Exception as e:
                report["review"].append((p.name, f"{hub} ({how}), filing failed: {e}"))
        else:
            report["proposed"].append((p.name, f"{hub} ({how})"))
    for section, items in report.items():
        if items:
            print(f"\n{section.upper()} ({len(items)})")
            for name, why in items:
                print(f"  - {name}\n      {why}")
    print("\n" + json.dumps({k: len(v) for k, v in report.items()}))


if __name__ == "__main__":
    main()
