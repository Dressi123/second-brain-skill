#!/bin/bash
# SessionStart hook: two cheap checks, no headless subprocess, no
# permission complexity -- just informational nudges injected into the
# new session's context for the live interactive session to act on (or
# not). Never decides anything autonomously.
#
# 1. Pending Inbox items (Desktop/iOS captures awaiting triage) -- nudge
#    to offer the second-brain skill's "triage inbox" operation.
# 2. Staleness of the status dashboard -- if it's been >24h since it was
#    last generated AND there's been real hook activity since then,
#    nudge to offer regenerating it. Never auto-runs it.
set -uo pipefail

# Recursion guard: the SessionEnd finalize hook makes headless `claude -p`
# calls, which are themselves Claude Code invocations and would otherwise
# re-trigger this SessionStart hook (and its own SessionEnd on completion),
# fanning out indefinitely. SECOND_BRAIN_HOOK is exported before any such
# nested call so this hook no-ops immediately for it.
if [ -n "${SECOND_BRAIN_HOOK:-}" ]; then
  exit 0
fi

VAULT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault"
INBOX="$VAULT/Inbox"
HELPERS="$HOME/.claude/skills/second-brain/helpers"
LOG="$HELPERS/session_hooks.log"
STATUS_MARKER="$HELPERS/.last_status_view"

inbox_count=$(find "$INBOX" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
echo "$(date '+%F %T') - SessionStart: inbox check, $inbox_count pending" >> "$LOG"

status_nudge=0
if [ -f "$LOG" ]; then
  log_epoch=$(stat -f %m "$LOG" 2>/dev/null || echo 0)
  if [ ! -f "$STATUS_MARKER" ]; then
    status_nudge=1
  else
    marker_epoch=$(stat -f %m "$STATUS_MARKER" 2>/dev/null || echo 0)
    now_epoch=$(date +%s)
    age=$(( now_epoch - marker_epoch ))
    if [ "$age" -gt 86400 ] && [ "$log_epoch" -gt "$marker_epoch" ]; then
      status_nudge=1
    fi
  fi
fi

if [ "$inbox_count" -gt 0 ] || [ "$status_nudge" -eq 1 ]; then
  python3 -c "
import json, sys
inbox_count, status_nudge = sys.argv[1], sys.argv[2]
parts = []
if int(inbox_count) > 0:
    parts.append(
        f'The second-brain vault Inbox has {inbox_count} untriaged item(s) '
        'waiting (captures from Desktop/iOS). Early in this session, '
        'consider offering to triage them via the second-brain skill\'s '
        '\"triage inbox\" operation.'
    )
if status_nudge == '1':
    parts.append(
        'It has been a while since the vault status dashboard was last '
        'generated, and there has been hook activity since then. Consider '
        'mentioning that the user can regenerate it '
        '(python3 ~/.claude/skills/second-brain/helpers/brain_status.py) '
        'if he wants a current view -- do not run it yourself unasked.'
    )
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': ' '.join(parts),
    }
}))
" "$inbox_count" "$status_nudge"
fi
exit 0
