#!/usr/bin/env python3
"""Generate a local HTML status dashboard for the second-brain vault and
open it in the default browser. A snapshot at generation time, not a live
view -- there is no persistent process, just a file regenerated on demand
(run this again any time for a fresh one).

Usage: brain_status.py [--no-open]
"""
import re
import subprocess
import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from urllib.parse import quote

from vault_paths import VAULT  # honors $SECOND_BRAIN_VAULT; defaults to the iCloud vault
VAULT_NAME = VAULT.name  # Obsidian's vault= param is the vault folder's own name
HELPERS = Path.home() / ".claude" / "skills" / "second-brain" / "helpers"
LOG = HELPERS / "session_hooks.log"
TEMPLATE = HELPERS / "dashboard_template.html"
OUT = HELPERS / "brain-status.html"
STATUS_MARKER = HELPERS / ".last_status_view"


def read_taxonomy():
    out = subprocess.run(
        ["python3", str(HELPERS / "list_taxonomy.py")],
        capture_output=True, text=True, timeout=45,
    ).stdout
    projects = re.findall(r"`([\w-]+)`\s*→\s*(.+)", out.split("## Topics")[0])
    topics = re.findall(r"`([\w-]+)`\s*→\s*(.+)", out.split("## Topics")[1]) if "## Topics" in out else []
    return projects, topics


def obsidian_uri(path: Path) -> str:
    """Native Obsidian URI (no plugin needed) to open this file directly
    in the app, rather than a plain file:// link that just opens whatever
    the OS defaults .md to (usually not Obsidian)."""
    rel_no_ext = str(path.relative_to(VAULT))[: -len(".md")]
    return f"obsidian://open?vault={quote(VAULT_NAME)}&file={quote(rel_no_ext, safe='/')}"


def h1_title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return path.stem


def read_recent_sessions(n=6):
    sessions_dir = VAULT / "Claude Archive" / "Sessions"
    files = [p for p in sessions_dir.glob("*.md")] if sessions_dir.exists() else []
    files.sort(key=lambda p: p.name, reverse=True)
    items = []
    for p in files[:n]:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
        date = m.group(1) if m else "?"
        items.append((date, h1_title(p), p))
    return items, len(files)


def read_inbox():
    inbox_dir = VAULT / "Inbox"
    files = sorted(inbox_dir.glob("*.md")) if inbox_dir.exists() else []
    return [(h1_title(p), p) for p in files]


DRAFT_STALE_AFTER = timedelta(hours=2)

# A finalize takes ~45s on a short session and ~270s on a five-hour one (one
# `claude -p` over the whole transcript digest, two if the summary fails
# validation). The SessionEnd hook's configured timeout is 900s, so nothing can
# still be running past that plus slack. Below this age an invoked-but-
# unfinished finalize is in flight, not dead -- without the grace period,
# regenerating the dashboard during those minutes reports a perfectly healthy
# session as 'crashed', which is exactly what happened on 2026-08-28.
FINALIZE_GRACE = timedelta(minutes=20)


def log_ts(line: str):
    """Leading '%Y-%m-%d %H:%M:%S' written by the hooks' `date '+%F %T'`.
    Naive local time, matching datetime.now() -- the hooks never write UTC."""
    try:
        return datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def last_ts_containing(log_text: str, needle: str):
    for line in reversed(log_text.splitlines()):
        if needle in line:
            return log_ts(line)
    return None


def read_drafts():
    """Inspect Sessions/.drafts/ for drafts whose SessionEnd never completed.

    The Stop hook rewrites a draft every turn; the SessionEnd hook is what
    promotes it into a real summary and then deletes it (`rm -f "$draft"` is
    its last line). So a draft outliving its session means the finalize never
    finished -- and because nothing else ever sweeps this directory, it stays
    there indefinitely. Five states, distinguished from the log:

      orphaned   - 'done for' logged after the last invoke, yet the draft is
                   still here (the delete failed)
      crashed    - finalize invoked, never completed, and too old to still be
                   running
      finalizing - finalize invoked within FINALIZE_GRACE: still in flight
      stale      - no finalize ever ran, and the file has stopped changing
      active     - no finalize yet but written recently: a live session, fine

    'done for' is compared by position against the last invoke rather than
    merely tested for presence: a session that was finalized and is now being
    finalized again would otherwise read 'orphaned' forever.
    """
    drafts_dir = VAULT / "Claude Archive" / "Sessions" / ".drafts"
    if not drafts_dir.exists():
        return []
    log_text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
    now = datetime.now()
    out = []
    for p in sorted(drafts_dir.glob("*.md")):
        sid = p.stem
        try:
            age = now - datetime.fromtimestamp(p.stat().st_mtime)
        except OSError:
            continue
        invoked = last_ts_containing(log_text, f"invoking claude -p to finalize {sid}")
        done = last_ts_containing(log_text, f"SessionEnd: done for {sid}")
        if invoked and done and done >= invoked:
            state, note = "orphaned", "finalized, but the draft was left behind"
        elif invoked and now - invoked <= FINALIZE_GRACE:
            state, note = "finalizing", "finalize in flight, started just now"
        elif invoked:
            state, note = "crashed", "finalize started, never completed"
        elif done:
            state, note = "orphaned", "finalized, but the draft was left behind"
        elif age > DRAFT_STALE_AFTER:
            state, note = "stale", "no finalize ever ran"
        else:
            state, note = "active", "live session in progress"
        out.append({"sid": sid, "state": state, "note": note, "age": age, "path": p})
    # Problems first, then newest; 'active' is informational so it sinks.
    order = {"crashed": 0, "orphaned": 1, "stale": 2, "finalizing": 3, "active": 4}
    out.sort(key=lambda d: (order[d["state"]], d["age"]))
    return out


def human_age(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 120:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 172800:
        return f"{secs // 3600}h ago"
    return f"{delta.days}d ago"


def vault_totals():
    def count(rel):
        d = VAULT / rel
        return len(list(d.glob("*.md"))) if d.exists() else 0

    return {
        "bulk_export": count("Claude Archive/Bulk export"),
        "notes": count("Notes"),
    }


def parse_hook_log():
    if not LOG.exists():
        return {
            "stop": {"last": None, "note": "no log file yet"},
            "session_end": {"last": None, "note": "no log file yet", "recent_failures": 0},
            "session_start": {"last": None, "note": "no log file yet"},
        }
    lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

    def last_matching(pattern):
        last = None
        for line in lines:
            if pattern in line:
                m = ts_re.match(line)
                if m:
                    last = m.group(1)
        return last

    recent_failures = sum(1 for line in lines[-200:] if "still invalid after fix attempt" in line)

    return {
        "stop": {"last": last_matching("updated draft for session")},
        "session_end": {
            "last": last_matching("SessionEnd: done for"),
            "recent_failures": recent_failures,
        },
        "session_start": {"last": last_matching("SessionStart: inbox check")},
    }


def freshness(last_str):
    """Return (status, human_label) for a 'last seen' timestamp string."""
    if not last_str:
        return "warn", "never observed"
    last = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
    age = datetime.now() - last
    if age < timedelta(hours=6):
        label = "just now" if age < timedelta(minutes=2) else f"{int(age.total_seconds() // 60)}m ago"
        return "good", label
    if age < timedelta(days=2):
        return "good", f"{int(age.total_seconds() // 3600)}h ago"
    if age < timedelta(days=14):
        return "warn", f"{age.days}d ago"
    return "warn", f"{age.days}d ago"


def render(projects, topics, sessions, sessions_total, inbox, totals, hooks, drafts):
    now = datetime.now().strftime("%A, %B %-d, %Y — %-I:%M %p")

    def hook_row(name, key, extra=""):
        info = hooks[key]
        status, label = freshness(info.get("last"))
        return (
            f'<div class="hook-row">'
            f'<span class="pill pill-{status}"></span>'
            f'<span class="hook-name">{escape(name)}</span>'
            f'<span class="hook-time">{escape(label)}</span>'
            f'{extra}</div>'
        )

    failures = hooks["session_end"].get("recent_failures", 0)
    fail_note = (
        f'<span class="hook-note text-critical">{failures} validation retry(s) recently</span>'
        if failures else ""
    )

    hook_rows = "\n      ".join([
        hook_row("Stop (draft save)", "stop"),
        hook_row("SessionEnd (finalize)", "session_end", fail_note),
        hook_row("SessionStart (inbox check)", "session_start"),
    ])

    if sessions:
        session_items = "\n        ".join(
            f'<li><span class="session-date">{escape(date)}</span>'
            f'<a class="session-link" href="{escape(obsidian_uri(path))}">{escape(title)}</a></li>'
            for date, title, path in sessions
        )
        recent_html = f'<ul class="timeline">\n        {session_items}\n      </ul>'
    else:
        recent_html = '<p class="empty">No sessions yet.</p>'

    if inbox:
        inbox_items = "\n        ".join(
            f'<li><a class="session-link" href="{escape(obsidian_uri(path))}">{escape(title)}</a></li>'
            for title, path in inbox
        )
        inbox_section = (
            f'<section class="panel panel-inbox">'
            f'<h2>Inbox — needs triage <span class="count-badge">{len(inbox)}</span></h2>'
            f'<ul class="timeline">\n        {inbox_items}\n      </ul>'
            f'</section>'
        )
    else:
        inbox_section = ""

    # Drafts: data only. The panel's markup, heading, tooltip and empty state
    # all live in dashboard_template.html -- this just fills the rows, the
    # badge text and the panel's state class. read_drafts() already sorted
    # problems first, active last.
    # 'finalizing' is in-flight, not a problem -- it must not reach the badge,
    # or every dashboard run during a finalize reports a stuck session.
    healthy = {"active", "finalizing"}
    stuck_n = sum(1 for d in drafts if d["state"] not in healthy)
    pill = {"crashed": "critical", "orphaned": "critical", "stale": "warn",
            "finalizing": "good", "active": "good"}
    draft_rows = "\n        ".join(
        f'<li><span class="pill pill-{pill[d["state"]]}"></span>'
        f'<span class="draft-state draft-{d["state"]}">{escape(d["state"])}</span>'
        f'<code class="draft-sid">{escape(d["sid"][:8])}</code>'
        f'<span class="draft-note">{escape(d["note"])}</span>'
        f'<a class="draft-link" href="{escape(obsidian_uri(d["path"]))}">open</a>'
        f'<span class="hook-time">{escape(human_age(d["age"]))}</span></li>'
        for d in drafts
    )
    if not drafts:
        drafts_badge = "clean"
        drafts_state = "ok"
    elif stuck_n:
        drafts_badge = f"{stuck_n} stuck"
        drafts_state = "alert"
    elif any(d["state"] == "finalizing" for d in drafts):
        drafts_badge = "finalizing"
        drafts_state = "ok"
    else:
        drafts_badge = f"{len(drafts)} active"
        drafts_state = "ok"

    project_chips = " ".join(f'<span class="chip">{escape(name)}</span>' for _, name in projects)
    topic_chips = " ".join(f'<span class="chip chip-topic">{escape(name)}</span>' for _, name in topics)

    template = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "{{GENERATED_AT}}": escape(now),
        "{{PROJECTS_COUNT}}": str(len(projects)),
        "{{TOPICS_COUNT}}": str(len(topics)),
        "{{SESSIONS_COUNT}}": str(sessions_total),
        "{{INBOX_COUNT}}": str(len(inbox)),
        "{{NOTES_COUNT}}": str(totals["notes"]),
        "{{BULK_EXPORT_COUNT}}": str(totals["bulk_export"]),
        "{{HOOK_ROWS}}": hook_rows,
        "{{RECENT_SESSIONS}}": recent_html,
        "{{INBOX_SECTION}}": inbox_section,
        "{{DRAFT_ROWS}}": draft_rows,
        "{{DRAFTS_BADGE}}": escape(drafts_badge),
        "{{DRAFTS_STATE}}": drafts_state,
        "{{PROJECT_CHIPS}}": project_chips,
        "{{TOPIC_CHIPS}}": topic_chips,
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def main():
    projects, topics = read_taxonomy()
    sessions, sessions_total = read_recent_sessions()
    inbox = read_inbox()
    totals = vault_totals()
    hooks = parse_hook_log()
    drafts = read_drafts()

    html = render(projects, topics, sessions, sessions_total, inbox, totals, hooks, drafts)
    OUT.write_text(html, encoding="utf-8")
    STATUS_MARKER.write_text(datetime.now().isoformat(), encoding="utf-8")

    print(f"Wrote {OUT}")
    if "--no-open" not in sys.argv:
        subprocess.run(["open", str(OUT)])


if __name__ == "__main__":
    main()
