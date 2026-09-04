#!/bin/bash
# Stop hook: fires after every assistant turn. Keeps a lightweight,
# informal running draft of the in-progress session up to date, so work
# isn't lost if the session ends abnormally (crash, force quit).
# Pure text generation (no tools) via Haiku -- cheap and fast.
set -uo pipefail

# Recursion guard: this hook itself calls `claude -p` below, which is a
# Claude Code invocation that would otherwise re-trigger Stop/SessionEnd
# hooks on itself (and those on their own nested calls, etc). Any nested
# invocation exports SECOND_BRAIN_HOOK so it no-ops immediately here.

if [ -n "${SECOND_BRAIN_HOOK:-}" ]; then
  exit 0
fi

# Publish whatever this session wrote to the vault, so Claude on the iPhone
# sees it without waiting for the next session. On a trap, not a line at the
# bottom: this script has several early-exit paths, and a summary that was
# written but never pushed is invisible from the phone.
trap '"$HOME/.claude/skills/second-brain/helpers/vault_git_sync.sh" push >/dev/null 2>&1 || true' EXIT

CLAUDE_BIN="${CLAUDE_CODE_EXECPATH:-$HOME/.local/bin/claude}"
VAULT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault"
DRAFT_DIR="$VAULT/Claude Archive/Sessions/.drafts"
LOG="$HOME/.claude/skills/second-brain/helpers/session_hooks.log"

mkdir -p "$DRAFT_DIR"

input=$(cat)
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
session_id=$(echo "$input" | jq -r '.session_id // empty')

if [ -z "$transcript" ] || [ ! -f "$transcript" ] || [ -z "$session_id" ]; then
  exit 0
fi

lines=$(wc -l < "$transcript" | tr -d ' ')
if [ "$lines" -lt 4 ]; then
  exit 0
fi

draft="$DRAFT_DIR/${session_id}.md"
existing=""
[ -f "$draft" ] && existing=$(cat "$draft")

recent=$(tail -n 60 "$transcript")

prompt=$(printf 'You maintain a lightweight running draft note for an in-progress Claude Code session, so nothing is lost if it ends abnormally. This is NOT the final curated note -- just terse continuity notes.\n\nExisting draft (may be empty):\n---\n%s\n---\n\nMost recent transcript activity (JSONL, one event per line):\n---\n%s\n---\n\nRewrite the draft as a short bullet list: what is being worked on, key decisions/facts so far, open threads. Merge in anything new from the recent activity. Keep it under 200 words. Output ONLY the new draft content -- no preamble, no commentary, no code fences.' "$existing" "$recent")

# Lean invocation. Two things going on here:
#
# 1. `env -u ANTHROPIC_API_KEY` — credential precedence is API key BEFORE
#    OAuth ("first match wins"), and Claude Code puts a key into its own
#    environment, which child processes inherit. Without this, every hook
#    call bills pay-per-token API credits even when logged into a
#    subscription. Unsetting it lets the OAuth/keychain credential win.
#
# 2. `--tools ""` + `--strict-mcp-config` + `--system-prompt` — measured to
#    cut injected harness from ~27,200 tokens to ~2,500 (-91%). This hook is
#    pure text generation: it needs no tools, no MCP servers, and no CLAUDE.md
#    /skill listings, yet was paying for all of them on every assistant turn.
#    The real instructions live in $prompt (the user message), so replacing the
#    default system prompt is safe. Worth keeping on a subscription too —
#    fewer tokens means less rate-limit burn and lower latency.
new_draft=$(SECOND_BRAIN_HOOK=1 env -u ANTHROPIC_API_KEY "$CLAUDE_BIN" -p "$prompt" \
  --model claude-haiku-4-5-20251001 \
  --tools "" \
  --strict-mcp-config \
  --system-prompt "You write terse continuity notes. Output only the requested content." \
  2>>"$LOG")

if [ -n "$new_draft" ]; then
  printf '%s\n' "$new_draft" > "$draft"
  echo "$(date '+%F %T') - updated draft for session $session_id" >> "$LOG"
fi
exit 0
