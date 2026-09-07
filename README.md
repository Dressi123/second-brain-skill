# Second brain

A Claude Code skill that turns a folder of markdown into a memory Claude actually
uses. Ask *"what did we decide about X?"* in any repo and it finds the note; end a
real work session and it writes the summary itself and files it under the right
project.

It is plain markdown all the way down — Obsidian on top is optional (nice for the
graph view and mobile editing, but nothing here depends on it).

## What you get

**Tier 1 — the vault and the skill.** Claude can search your notes by meaning
rather than keyword, load a project's history when you open its repo, and file
new notes correctly. Ten minutes to set up, and this is most of the value.

**Tier 2 — hooks.** Sessions save themselves. A background draft updates every
turn, and when the session ends Claude promotes it into a real summary, links it
to its project hub, and validates the frontmatter. You do nothing.

**Tier 3 — phone and web.** The vault mirrors to a private GitHub repo and a small
Vercel app serves it to Claude on iOS and claude.ai, so you can capture a note
from your phone and it is on your Mac by the next session. Optional, and the
fiddliest part.

## Requirements

macOS, Python 3.12+, git, [Claude Code](https://claude.com/claude-code), and `jq`
(`brew install jq`) if you want Tier 2. Tier 3 additionally wants a GitHub
account and a free Vercel account.

---

## Tier 1 — vault and skill

```bash
git clone https://github.com/Dressi123/second-brain-skill.git ~/.claude/skills/second-brain
cd ~/.claude/skills/second-brain
./bootstrap.sh
```

`bootstrap.sh` is the whole setup. It was written for one Mac, so the clone is
full of that Mac's paths and its owner's name; the script rewrites every one of
them to yours, then creates the vault folders and the three templates the helper
scripts expect to find. It is safe to run twice, and `--dry-run` shows you what it
would touch first.

By default the vault goes to the iCloud Obsidian location
(`~/Library/Mobile Documents/iCloud~md~obsidian/Documents/<vault>`). Anywhere else
is fine:

```bash
./bootstrap.sh --vault ~/Documents/Brain --name "Sam"
```

It finishes by running the vault index, which is the real smoke test — if it
prints a header and no traceback, the skill works. Then:

```bash
# create your first project hub
python3 ~/.claude/skills/second-brain/helpers/new_hub.py \
  --type project --id my-app --name "My App" --description "What it is, in a sentence."
```

Open Claude Code anywhere and ask *"what's in my second brain?"*. It should read
`SKILL.md`, run the index, and tell you about `my-app`.

### Optional: make Claude reach for it on its own

Add to `~/.claude/CLAUDE.md` (create it if it doesn't exist) so every session
knows the vault exists:

```markdown
## The second brain

I keep a personal knowledge base at `<your vault path>` — plain markdown.
Use the **`second-brain` skill** at `~/.claude/skills/second-brain/` for all
vault operations: saving session summaries, loading project context at session
start, creating hubs, and answering "what did we figure out about X?".
Invoke it at session start in a real project directory, when I mention the
vault, and at the end of a session where real work happened.
```

### How the vault is organised

```
Projects/<Display Name>.md        one hub per active project
Notes/Topics/<Display Name>.md    thematic hubs (things that aren't projects)
Claude Archive/Sessions/          session summaries land here
Templates/                        the session-summary template lives here
Inbox/                            quick captures awaiting triage
Notes/, Daily/                    everything else
```

Every note carries frontmatter naming exactly one hub (`project: my-app` or
`topic: some-topic`) plus matching tags, and links back to its hub with a
wikilink. That is what makes the index work — `SKILL.md` documents the rules and
Claude follows them, so you rarely write frontmatter by hand.

The scripts under `helpers/` are the API. `vault_index.py` prints the whole vault
as a ~3k-token map, which is how Claude finds things; `search_notes.py` is
literal-match drill-down for when you already know the phrasing. Reaching for
search first is how you conclude something isn't in the vault when it is — the
skill says so, at length, because it was learned the hard way.

---

## Tier 2 — hooks (sessions save themselves)

Merge this into `~/.claude/settings.json`. `bootstrap.sh` prints this same block
with your paths already filled in, so copy it from there rather than editing by
hand:

```jsonc
{
  "permissions": {
    "additionalDirectories": ["<your vault path>"]
  },
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command",
      "command": "bash ~/.claude/skills/second-brain/helpers/session_start_inbox_check.sh",
      "timeout": 15 }] }],
    "Stop": [{ "hooks": [{ "type": "command",
      "command": "bash ~/.claude/skills/second-brain/helpers/session_stop_draft_hook.sh",
      "timeout": 120, "async": true }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command",
      "command": "bash ~/.claude/skills/second-brain/helpers/session_end_finalize_hook.sh",
      "timeout": 900, "async": true }] }]
  }
}
```

What each one costs, honestly:

- **SessionStart** — reads `Inbox/` and, if anything is pending, mentions it. Cheap.
- **Stop** — after every assistant turn, rewrites a draft summary at
  `Claude Archive/Sessions/.drafts/<session-id>.md`. Async, so it never blocks you,
  but it is a Claude invocation per turn.
- **SessionEnd** — promotes the draft into a real summary, links it to its hub, and
  validates it. Up to 900 s, async, and it decides for itself whether the session
  was worth saving.

There is a fourth hook, `vault_pretool_pull_hook.sh` on `PreToolUse`, that keeps
the vault in sync with GitHub around every read and write. **Only add it if you do
Tier 3** — without a GitHub mirror it has nothing to sync:

```jsonc
"PreToolUse": [{ "matcher": "Read|Write|Edit|Bash", "hooks": [{ "type": "command",
  "command": "bash ~/.claude/skills/second-brain/helpers/vault_pretool_pull_hook.sh",
  "timeout": 20 }] }]
```

It fires on every Read/Write/Edit/Bash call but exits in milliseconds unless the
path actually points at the vault, so the cost is a `jq` call per tool use.

### Checking the hooks are alive

```bash
python3 ~/.claude/skills/second-brain/helpers/brain_status.py
```

Builds an HTML dashboard and opens it. Read the **Session drafts** panel: a row
marked `active` is live proof the Stop hook is running. `stale`, `crashed` or
`orphaned` mean a leftover — nothing sweeps `.drafts/`, so delete those once
you've confirmed the work got captured. `helpers/session_hooks.log` has the raw
trail when something looks wrong.

---

## Tier 3 — phone and web access

Two moving parts: the vault mirrors to a **private** GitHub repo, and a small
Vercel app serves that repo to Claude as an MCP connector.

### 1. Mirror the vault to GitHub

Create an empty **private** repo (e.g. `second-brain-vault`) and push the vault to
it. The git directory deliberately lives *outside* the vault, at
`~/.second-brain-git`, so Obsidian and iCloud never see a `.git/` folder:

```bash
VAULT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault"  # yours
git init --bare -b main ~/.second-brain-git   # -b main, or the first push fails
git --git-dir=$HOME/.second-brain-git --work-tree="$VAULT" remote add origin \
  https://github.com/<you>/second-brain-vault.git
git --git-dir=$HOME/.second-brain-git --work-tree="$VAULT" add -A
git --git-dir=$HOME/.second-brain-git --work-tree="$VAULT" commit -m "initial vault"
git --git-dir=$HOME/.second-brain-git --work-tree="$VAULT" push -u origin main
```

Put a `.gitignore` in the vault root that excludes `.DS_Store`,
`.obsidian/workspace*.json` and binaries (`*.png`, `*.pdf`, `Attachments/`, …).
Markdown-only is what keeps git a sane sync backend.

From then on `helpers/vault_git_sync.sh pull|push|sync` is the bridge, and the
PreToolUse hook above calls it for you. It is deliberately **not** a launchd timer:
macOS denies background agents access to `~/Library/Mobile Documents`, so a timer
gets "Operation not permitted" on every file. It runs from processes that already
have vault access instead.

### 2. Deploy the connector

`vercel/README.md` has the full deploy, and it is accurate — follow it. Two things
it assumes you've already done:

- Step 1 above exists (the app reads the vault *from GitHub*, not from your Mac).
- You set `VAULT_REPO` to **your** repo. It defaults to the original author's
  private vault, which your deploy cannot read.

You'll need a fine-grained GitHub PAT with Contents read+write scoped to that one
repo — not `gh auth token`, which carries far broader scopes. Then add
`<your-vercel-url>/mcp` as a connector in Claude's settings.

Once it's up, `capture_note` from your phone drops a note into `Inbox/`, and the
next Claude Code session on your Mac offers to file it.

### Claude Desktop, locally

Separate and much simpler — `mcp-server/` is a stdio MCP server exposing the same
six tools off the local disk. Point Claude Desktop's config at
`mcp-server/server.py` if you want the vault there too. Claude Code doesn't need
it: the skill reads the files directly, which is always faster and never a sync
behind.

---

## Troubleshooting

**Hooks silently do nothing.** They shell out to the `claude` binary. Check
`which claude` matches the `CLAUDE_BIN` line in
`helpers/session_stop_draft_hook.sh`; `bootstrap.sh` sets it from your `PATH`, but
a later install can move it. Also confirm `jq` is installed.

**A helper can't find the vault.** Everything Python reads the path from
`helpers/vault_paths.py`, which `bootstrap.sh` rewrites. `SECOND_BRAIN_VAULT` in
your environment overrides it. The shell hooks hold their own copy of the path —
`grep -rn "MyVault" helpers/` finds any that got missed.

**Claude ignores the skill.** Confirm it's at `~/.claude/skills/second-brain/` with
a readable `SKILL.md`, and that `bootstrap.sh` replaced the original author's name
in the description — the frontmatter description is what Claude matches against.

**Sync stops.** `vault_git_sync.sh` refuses to touch a repo left mid-rebase or
mid-merge, by design. Check `~/.second-brain-git/sync.log`, resolve by hand, and
it resumes.

---

## Layout

```
SKILL.md            the instructions Claude reads — the actual product
bootstrap.sh        makes this clone yours
helpers/            vault_index, search_notes, list_taxonomy, validate,
                    new_hub, add_session_to_hub, brain_status,
                    vault_git_sync, + the four session hooks
mcp-server/         stdio MCP server for Claude Desktop (local disk)
vercel/             hosted MCP server for iOS/web (reads the GitHub mirror)
agents/             Codex agent card
```

`SKILL.md` is worth reading start to finish even if you never touch the code. It
is the design document as much as the instructions, and most of it exists because
something went wrong first.

## A note on forking

This is one person's setup, shared because it works, not a product. The
conventions in `SKILL.md` — hub IDs, the frontmatter shape, "neither a keyword
search nor a guess" — are opinions that earned their place; change them if yours
differ, but change them in `SKILL.md`, which is the one file everything else
follows.

The vault repo referenced in `vercel/` is private personal notes. Make your own.
