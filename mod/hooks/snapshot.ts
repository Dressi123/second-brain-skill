// Inline Python run by the mod. It reuses the second-brain helpers so no vault
// logic is duplicated here. Argument 1: "snap" (print JSON) or "regen" (rebuild
// the HTML dashboard without opening it).
export const SNAPSHOT_PY = String.raw`
import json, os, re, subprocess, sys
from datetime import datetime
from pathlib import Path

H = Path.home() / ".claude" / "skills" / "second-brain" / "helpers"
sys.path.insert(0, str(H))

if sys.argv[1] == "regen":
    r = subprocess.run([sys.executable, str(H / "brain_status.py"), "--no-open"], capture_output=True, text=True)
    print(json.dumps({"ok": r.returncode == 0, "err": r.stderr[-300:]}))
    sys.exit(0)

if sys.argv[1] in ("triage-dry", "triage-apply"):
    import shutil
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    cmd = [uv, "run", "--script", str(H / "triage_inbox.py")] + (["--apply"] if sys.argv[1] == "triage-apply" else [])
    res = {"ok": False, "err": "", "noKey": False, "proposed": [], "review": [], "filed": []}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=110)
        res["ok"] = r.returncode == 0
        res["err"] = r.stderr[-300:]
        res["noKey"] = "no TypeSafe key" in r.stdout
        cur = None
        item = None
        for line in r.stdout.splitlines():
            m = re.match(r"^(PROPOSED|REVIEW|FILED) \(\d+\)$", line)
            if m:
                cur = m.group(1).lower()
                item = None
                continue
            if line.startswith("{"):
                cur = None
                continue
            if cur and line.startswith("  - "):
                item = {"file": line[4:].strip(), "why": ""}
                res[cur].append(item)
            elif cur and item is not None and line.startswith("      "):
                item["why"] = line.strip()
    except Exception as ex:
        res["err"] = str(ex)[:200]
    print(json.dumps(res))
    sys.exit(0)

import brain_status as b
from vault_paths import VAULT

def norm(s):
    return "".join(c for c in s.lower() if c.isalnum())

def front(p):
    try:
        t = p.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return ""
    m = re.match(r"---\n(.*?)\n---", t, re.S)
    return m.group(1) if m else ""

def find_hub(want):
    files = list((VAULT / "Projects").glob("*.md")) + list((VAULT / "Notes" / "Topics").glob("*.md"))
    for f in files:
        m = re.search(r"^id:\s*(\S+)", front(f), re.M)
        if m and norm(m.group(1)) == want:
            return f, m.group(1)
    for f in files:
        fm = front(f)
        m = re.search(r"^id:\s*(\S+)", fm, re.M)
        inline = re.search(r"^aliases:[ \t]*\[(.*?)\]", fm, re.M)
        block = re.search(r"^aliases:[ \t]*\n((?:[ \t]*-.*(?:\n|$))+)", fm, re.M)
        vals = inline.group(1).split(",") if inline else ([l.strip()[1:] for l in block.group(1).splitlines()] if block else [])
        if m and any(norm(v.strip().strip("'\"")) == want for v in vals):
            return f, m.group(1)
    return None, None

hub_file, hub_id = find_hub(norm(os.path.basename(os.getcwd())))
hub_sessions = []
if hub_id:
    for p in sorted((VAULT / "Claude Archive" / "Sessions").glob("*.md"), reverse=True):
        fm = front(p)
        if re.search(r"^(project|topic):\s*" + re.escape(hub_id) + r"\s*$", fm, re.M):
            hub_sessions.append({"date": p.name[:10], "title": b.h1_title(p), "uri": b.obsidian_uri(p)})
            if len(hub_sessions) >= 6:
                break

stale = False
if b.LOG.exists():
    if not b.STATUS_MARKER.exists():
        stale = True
    else:
        mk = b.STATUS_MARKER.stat().st_mtime
        stale = (datetime.now().timestamp() - mk) > 86400 and b.LOG.stat().st_mtime > mk

hooks = b.parse_hook_log()
print(json.dumps({
    "vault": str(VAULT),
    "helpers": str(H),
    "inbox": [{"title": t, "file": q.name, "uri": b.obsidian_uri(q)} for t, q in b.read_inbox()],
    "hub": hub_file.stem if hub_file else None,
    "hubSessions": hub_sessions,
    "drafts": [{"sid": d["sid"][:8], "state": d["state"], "note": d["note"], "path": str(d["path"])} for d in b.read_drafts()],
    "hooks": [
        {"name": "Stop (draft save)", "last": hooks["stop"]["last"]},
        {"name": "SessionEnd (finalize)", "last": hooks["session_end"]["last"]},
        {"name": "SessionStart (inbox check)", "last": hooks["session_start"]["last"]},
    ],
    "dashboardStale": stale,
}))
`
