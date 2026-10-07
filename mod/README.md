# second-brain-mod

A Claude Code mod (a plugin of function hooks) for the second-brain vault. It
reuses the helpers in `~/.claude/skills/second-brain/helpers`, so it needs that
skill installed, and it finds the vault the way the skill does.

## What it does

- **Status band** above the prompt: inbox count, dashboard freshness, hub for the
  current directory, stuck drafts. `Hide` hides it; `/vault` brings it back.
- **`/vault` pane**: inbox, hub sessions, drafts and hook health, with buttons.
  - `Triage inbox` runs `triage_inbox.py` (dry run), shows `-> hub (score)` under each
    capture, then `File N` applies it.
  - `triage` on a row starts an `inbox-triage` subagent for that capture; its verdict
    shows inline with a `File under <hub>` button.
  - `open` opens a note in Obsidian; `Open dashboard` rebuilds and opens the HTML one.
- **`/vault-capture`**: saves the text you selected (fullscreen mode) to `Inbox/`.
- **Write guard**: denies a `Write` into `Inbox/`, `Claude Archive/Sessions/`, `Notes/`
  or `Daily/` that has no `date:` frontmatter. Fails open, and does not see `Edit`
  or writes through the remote MCP.
- **Dashboard auto-refresh**: rebuilds the HTML dashboard once per session when stale.

## Install

```
/plugin install second-brain-mod --marketplace Dressi123/second-brain-skill
```

or for development: `claude --plugin-dir /path/to/second-brain-mod`.

## Develop

```
claude plugin validate .
claude plugin test .
tsc -p .          # after the engine has loaded the mod once
```
