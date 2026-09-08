---
name: second-brain
description: The user's personal knowledge base ("second brain") -- an Obsidian vault of plain markdown on this Mac. Use in Claude Code or Codex for vault operations such as saving session summaries, loading project/topic context, creating hubs, querying past notes, and answering "what did we figure out about X?" Trigger on "second brain", "the vault", "save this session", "load context", "what did we work on for [project]", or clear references to ongoing work that may have saved context. Discover the live taxonomy with helpers/vault_index.py; never trust hardcoded hub lists.
---

# Second-brain operations

The user keeps a personal knowledge base in an Obsidian vault of plain markdown. Every helper resolves the vault's location itself; run `python3 ~/.claude/skills/second-brain/helpers/vault_paths.py` if you need the path literally, and write `<vault>` for it below. This skill is the single source of truth for how to interact with it.

**When running locally in Claude Code or Codex, always use the helper scripts
below — never the remote Second Brain MCP tools, even when they are offered.**
Those tools exist for clients without local filesystem access; the server behind
them reads the vault's GitHub-hosted copy, so it is a network round trip away and
can lag the working copy on this Mac. Local agents have the real vault on disk,
and these scripts read it directly.

The maintained skill source is `~/.claude/skills/second-brain`.
Codex discovers that same folder through a symlink at
`~/.codex/skills/second-brain`, so there is only one copy to keep up
to date. Commands below use the maintained source path and work from either agent.

Vault reads are safe to perform directly. Before a write, move, or deletion,
request filesystem write permission for the narrowest relevant vault path when
the active sandbox does not already grant it. Do not treat a sandbox denial as a
missing vault or silently fall back to the remote copy.

The scripts named `*_hook.sh` remain Claude Code-specific: they invoke the
Claude CLI and assume Claude's transcript format and timeout behavior. Do not
attach them to Codex hooks unchanged. In Codex, perform session saves through
the manual operation below until a Codex-specific finalizer is installed.

## Step 0 — always: orient with the vault index

Before doing anything substantive in the vault, run:

```bash
python3 ~/.claude/skills/second-brain/helpers/vault_index.py
```

This prints a compact map of the whole vault (~3k tokens): every curated note's path, hub, tags, and one-line description, grouped under its project/topic hub. **This is the primary way to find anything** — read the descriptions, pick the note that matches by meaning, then read that path with the available local file tools.

Useful flags: `--hub <id>` for one project/topic only (~1k tokens); `--archive` to also include the ~250 historical bulk-export conversations (~11k tokens). Their descriptions are only titles, but title + hub + tags retrieves reliably (measured 14/14 on questions worded nothing like their target note), so use `--archive` before `search_notes` when the curated tier comes up empty.

When you only need to *validate* that a hub ID exists (before writing or tagging a note) and don't need the full map, the cheaper call is:

```bash
python3 ~/.claude/skills/second-brain/helpers/list_taxonomy.py
```

**Use real IDs from one of these — never trust hardcoded lists, including any that might appear in CLAUDE.md or AGENTS.md.** The vault is the source of truth.

## Vault layout

- `Projects/<Display Name>.md` — project hubs (one per active project)
- `Notes/Topics/<Display Name>.md` — topic hubs (thematic groupings)
- `Claude Archive/Sessions/` — hand-curated session summaries (where new ones go)
- `Claude Archive/Bulk export/` — historical Claude.ai conversations (read-only)
- `Templates/Claude Session Summary.md` — template for new summaries
- `Inbox/` — pending Desktop/iOS captures awaiting triage (see "triage inbox" below)
- `Daily/`, `Notes/` — general PKM areas; `Notes/` (not `Notes/Topics/`) is also where triaged Inbox captures land

---

## Operation: load context (session start)

When starting a session that's clearly tied to ongoing work — a specific code repo, a recurring project, a topic from past chats:

1. Run `vault_index.py` to see what hubs exist and what's filed under each.
2. Try to match the working directory name, recent file content, README, or the user's first message to one of the project/topic IDs.
3. If you find a match:
   ```bash
   python3 ~/.claude/skills/second-brain/helpers/vault_index.py --hub <id>
   ```
   That returns the hub's description plus every note filed under it, newest first, each with a one-line description — no separate grep needed.
   - Read the 2–3 whose descriptions look most relevant.
   - In your first response, briefly mention: *"Loaded context from the [Project Name] hub and recent sessions."*
4. If no match, proceed without loading context.

For one-off questions, generic tasks, or quick lookups, skip this entirely. Don't burn tokens on context the user doesn't need.

---

## Operation: find a past note

**Default path — `vault_index.py` (Step 0), not keyword search.** When the user asks "what did we figure out about X", run the index, read the descriptions, and pick the note that matches by *meaning*. The index is ~3k tokens and covers every curated note, so this is one call and no guessing.

This ordering is deliberate and was measured. On a real question ("what did we decide about capturing notes when the Mac is asleep?"), keyword search returned **nothing** for 3 of 4 natural phrasings — `"Mac asleep"`, `"offline capture"`, `"server unreachable"` — while the correct note was immediately obvious from the index. Reaching for `search_notes.py` first is how you conclude something "isn't in the vault" when it is.

**Full-text drill-down — `search_notes.py`:**

```bash
python3 ~/.claude/skills/second-brain/helpers/search_notes.py "<query>"
```

Use it when you already know the exact phrasing you want (an error message, a command, a name, a specific term), or to dig into the ~250 bulk-export archive notes, where the index only has titles.

- Returns, per matching file, its path, the nearest heading, and a short excerpt -- **never whole files**. One hit per file.
- `--regex` for a regular expression instead of a literal substring; `--limit N` (default 20); `--context N` for excerpt length.
- Empty result ≠ absent. Literal matching means a note can exist under wording you didn't guess -- check `vault_index.py` before concluding anything isn't in the vault.

---

## Operation: show status dashboard

When the user asks to see the vault's status/health, or a Claude Code SessionStart hook nudges that it's been a while since they last checked:

```bash
python3 ~/.claude/skills/second-brain/helpers/brain_status.py
```

Generates a local HTML dashboard (taxonomy, recent sessions, Inbox pending, session drafts, hook health from the log) and opens it in the default browser. It's a snapshot at generation time, not live -- regenerate for a fresh view. Only run this when asked or when the SessionStart nudge suggests it; never run it unprompted just because it exists.

The **Session drafts** panel is the one to read for Claude Code hook health. The Stop hook rewrites `Sessions/.drafts/<session_id>.md` every turn; SessionEnd promotes it into a real summary and then deletes it. So each row means:

- `active` — a session in flight right now (green; this is the live proof the Stop hook is working)
- `stale` — no finalize ever ran, and the file stopped changing >2h ago
- `crashed` — finalize was invoked but never logged `done for`
- `orphaned` — finalize completed, yet the draft is still on disk

Anything other than `active` is a leftover: nothing ever sweeps `.drafts/`, so it will sit there indefinitely and is safe to delete once you've confirmed the work is captured elsewhere.

**When editing the dashboard: the UI lives in `dashboard_template.html`; `brain_status.py` only gathers data and fills `{{PLACEHOLDER}}` tokens.** Keep panel markup, headings, styling, and empty states in the template -- don't build sections in Python.

---

## Operation: save session summary (session end)

When the session has produced real work — decisions made, code shipped, a thread to pick up next time — write a summary.

1. Pick a date and a short slug describing the topic.
2. Identify the matching project ID or topic ID from current taxonomy. If none matches, see "suggest a new hub" below.
3. Write to: `<vault>/Claude Archive/Sessions/<YYYY-MM-DD>-<slug>.md`
4. Use this frontmatter shape (one of `project:` or `topic:`, not both):

   ```yaml
   ---
   date: YYYY-MM-DD
   project: <project-id>
   tags: [claude-session, project/<project-id>]
   ---
   ```

   (The one-line description of the session goes in the body's `## Topic` heading, not in frontmatter -- there is no free-text `topic:` frontmatter field for project work. A bare `topic:` key in frontmatter always means a topic-ID, per the taxonomy, never a description.)

   For topic-only work:
   ```yaml
   topic: <topic-id>
   tags: [claude-session, topic/<topic-id>]
   ```

5. Use the body structure from `<vault>/Templates/Claude Session Summary.md`.
6. **Always include an explicit wikilink to the hub in the body** — e.g. `[[Travel App (Wanderlust)]]`. This is what creates the graph edge that clusters the summary with its hub. Without it, the summary floats orphaned.
7. **Always link back from the hub to the session** — a forward link alone leaves the hub stale and the session undiscoverable from the hub side (this was a real, recurring miss — most 2026-08-24 sessions had no hub linking back to them). Run:

   ```bash
   python3 ~/.claude/skills/second-brain/helpers/add_session_to_hub.py \
     --hub "<path to hub note>" \
     --session "<session filename, no .md>" \
     --date <YYYY-MM-DD> \
     --summary "<one-line description>"
   ```

   This creates a `## Sessions` section on the hub if one doesn't exist yet, and adds the new session as the newest entry. Idempotent — safe to rerun.
8. After writing, validate:

   ```bash
   python3 ~/.claude/skills/second-brain/helpers/validate.py "<path to summary>"
   ```

   Fix any errors it reports.

Skip summaries entirely for quick lookups, single-question chats, or trivial fixes. The bar is: **would the user want to find this six months from now?** If unsure, skip.

---

## Operation: suggest a new hub

If a session is producing work that **deserves a permanent home** in the second brain and no existing hub matches it, **pause and ask:**

> "This feels like it could be a real ongoing thing — want me to spin up a hub note for it? I'll wire up the frontmatter and tag scheme so future sessions cluster correctly."

Triggers (any one is enough):

- The user explicitly says they're "starting" or "building" something new.
- It's the second or third session on the same topic.
- Multiple files / decisions / real intent — i.e. the user will want this context next time.
- He says something like "remember this," "we'll come back to this," or "save this."

Default is *no new hub* unless the work is genuinely substantial. Don't trigger on every chat.

---

## Operation: create a new hub

When the user approves a new hub:

```bash
python3 ~/.claude/skills/second-brain/helpers/new_hub.py \
  --type project \
  --id <new-id> \
  --name "<Display Name>" \
  --description "<one-paragraph description of the project>"
```

(Use `--type topic` for thematic categories rather than active projects.)

The script creates the hub note with proper YAML, validates the ID isn't taken, and uses kebab-case enforcement. Then write the session summary as usual, with `[[<Display Name>]]` in the body.

Because the skill always discovers taxonomy live from the vault, **no manual updates to CLAUDE.md, AGENTS.md, or this skill are needed** when a new hub is added. The new ID becomes available on the next `list_taxonomy.py` run.

---

## Operation: triage inbox

`Inbox/` holds quick captures from Desktop/iOS (via the `capture_note` MCP tool) waiting to be properly filed. In Claude Code, a SessionStart hook checks it and, if non-empty, adds a note to the session context -- that's the cue to offer triage early on. No Codex lifecycle hooks are configured by this shared skill, so triage when the user asks or when an explicitly requested vault status/check reveals pending captures; do not scan the Inbox on every unrelated task.

1. List `Inbox/*.md` (top level only -- ignore `.drafts/` or other hidden entries).
2. Run `list_taxonomy.py` to get the current, real project/topic IDs.
3. For each item, read it and decide:
   - **Clear match to an existing project/topic**: fix its frontmatter to use exactly one of `project:`/`topic:` with the real ID (a capture's `tags:` list may already hint at one, e.g. `topic/finance-housing` -- verify it's real via the taxonomy, don't just trust it blindly). Add a wikilink to the file from that hub's note, under whatever existing section fits (or a new `## Captures` section if none does). Then move the file to `Notes/<same filename>.md` and remove it from `Inbox/` -- this keeps the Inbox item count meaning "still pending," not "everything ever captured."
   - **No clear match -- looks like a genuinely new topic or project**: do not force it into an existing hub and do not auto-create one. Pause and ask, exactly like "suggest a new hub" above. Leave it in `Inbox/` until the user decides.
   - **Ambiguous, or too little content to tell**: ask rather than guess.
4. Report briefly what got filed and what's still waiting on a decision.

Same rule as saving session summaries: never invent a project/topic ID to make something fit.

---

## Hygiene

- Wikilinks use file basename only: `[[Travel App (Wanderlust)]]`, never the full path.
- Don't modify files in `Claude Archive/Bulk export/` — it's the historical archive.
- New session summaries go in `Claude Archive/Sessions/`, not anywhere else.
- Don't tag new files with `#claude-archive` or `#bulk-export` — those are export-only markers and pollute the graph.
- Hub note tag scheme: `[project-hub, project/<id>]` for projects, `[topic-hub, topic/<id>]` for topics.
- Project hubs live in `Projects/`. Topic hubs live in `Notes/Topics/`.
