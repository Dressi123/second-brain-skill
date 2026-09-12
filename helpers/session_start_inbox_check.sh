#!/bin/bash
# SessionStart hook: three cheap checks, no headless subprocess, no
# permission complexity -- a status line shown to the user as the session
# opens, plus the same status injected into the session's context for the
# model to act on (or not). Never decides anything autonomously.
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

. "$(dirname "${BASH_SOURCE[0]}")/vault_config.sh"   # sets VAULT
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

# 3. Whether the session's working directory has a hub: a project/topic
#    whose frontmatter id equals the directory's basename. Claude Code
#    passes the cwd on stdin; fall back to $PWD if that isn't readable.
cwd=$(python3 -c "import json,sys; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null)
cwd=${cwd:-$PWD}
hub_name=""
hub_file=$(grep -l -x "id: $(basename "$cwd")" "$VAULT"/Projects/*.md "$VAULT"/Notes/Topics/*.md 2>/dev/null | head -1)
if [ -n "$hub_file" ]; then
  hub_name=$(basename "$hub_file" .md)
fi

# Always report: systemMessage is shown to the user in the terminal as the
# session opens; additionalContext is the same status for the model, which
# can't speak until the user's first message.
python3 -c "
import json, sys
inbox_count, status_nudge, hub_name = int(sys.argv[1]), sys.argv[2] == '1', sys.argv[3]

shown = [f'Inbox {inbox_count} to triage' if inbox_count else 'Inbox empty']
shown.append('dashboard stale' if status_nudge else 'dashboard current')
shown.append(f'hub {hub_name}' if hub_name else 'no hub for this directory')

# A hook can't call tools or speak before the user's first message, so the
# nearest thing to an opening prompt is telling the model to ask with
# AskUserQuestion as the very first thing in its first reply.
options = []
if hub_name:
    options.append(f'Load {hub_name} context: run the second-brain skill\'s '
                   f'\"load context\" operation for the [[{hub_name}]] hub')
if inbox_count:
    options.append(f'Triage inbox: file the {inbox_count} Desktop/iOS captures '
                   'via the second-brain skill\'s \"triage inbox\" operation')
if status_nudge:
    options.append('Regenerate dashboard: run python3 '
                   '~/.claude/skills/second-brain/helpers/brain_status.py')

parts = [
    'The user has already been shown this vault status as the session opened: '
    + '; '.join(shown) + '.'
]
if options:
    options.append('Not now: skip all of it and go straight to their message')
    parts.append(
        'Before doing anything else in your first reply, call AskUserQuestion '
        '(header \"Second brain\", multiSelect true) asking which of these to '
        'do, one option per line below, label before the colon and '
        'description after. Then do what they picked, and then handle their '
        'first message. Do not run any of these unasked, and do not ask again '
        'later in the session.\n' + '\n'.join(options)
    )

print(json.dumps({
    'systemMessage': 'Second brain: ' + ' · '.join(shown),
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': ' '.join(parts),
    },
}))
" "$inbox_count" "$status_nudge" "$hub_name"
exit 0
