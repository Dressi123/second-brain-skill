#!/bin/bash
# SessionEnd hook: fires once when the session truly ends. Finalizes the
# running draft (if any) into a proper second-brain skill session summary
# -- correct frontmatter, hub wikilink, validated -- or decides the
# session was trivial and skips.
#
# Design note: the headless model is given NO Bash access at all -- only
# a bare "Read" allowedTools rule (empirically, Read is NOT unrestricted
# by default in headless -p mode, contrary to interactive-session
# behavior -- it needs to be explicitly granted same as anything else)
# and Write/Edit via --permission-mode acceptEdits. Taxonomy lookup, the
# recent-files list for dedup checking, and validation all happen here in
# the wrapper script instead, which has genuine unrestricted bash and
# needs no permission matching at all. This is the fix for two separate
# failures already hit in production: a --allowedTools "Edit(path)" rule
# silently not granting writes, and a --allowedTools "Bash(python3
# validate.py:*)" rule breaking the moment the model quoted the path
# differently than the rule's literal prefix expected. Neither class of
# bug can recur if the model never touches Bash for these steps at all --
# "Read" as a bare tool name has no path pattern to mismatch against.
set -uo pipefail

# Recursion guard: the two `claude -p` calls below are themselves Claude
# Code invocations and would otherwise re-trigger this same SessionEnd
# hook (and the Stop/SessionStart hooks) on completion, fanning out
# indefinitely -- confirmed empirically: a plain `claude -p "hi"` chained
# into SessionStart -> SessionEnd -> a nested finalize invocation. Any
# nested call exports SECOND_BRAIN_HOOK so this hook no-ops immediately.

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
SESSIONS="$VAULT/Claude Archive/Sessions"
DRAFT_DIR="$SESSIONS/.drafts"
HELPERS="$HOME/.claude/skills/second-brain/helpers"
VALIDATE_PY="$HELPERS/validate.py"
LOG="$HELPERS/session_hooks.log"

input=$(cat)
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
session_id=$(echo "$input" | jq -r '.session_id // empty')
reason=$(echo "$input" | jq -r '.reason // empty')

# reason=resume means the user switched to another session, not that this one
# is over -- they may well come back to it. Finalizing here would summarize
# partial work and (worse) delete the draft on the way out, so the eventual
# real end has to rebuild from scratch, and the dedup check would then see
# the premature summary as existing coverage and skip the complete one.
# Bail before that: leave the draft in place for the Stop hook to keep
# extending. If the session never does resume, the draft ages out and the
# status dashboard reports it as stale.
if [ "$reason" = "resume" ]; then
  echo "$(date '+%F %T') - SessionEnd: $session_id ended via resume, leaving draft for later" >> "$LOG"
  exit 0
fi

if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
  echo "$(date '+%F %T') - SessionEnd: no transcript, skipping" >> "$LOG"
  exit 0
fi

lines=$(wc -l < "$transcript" | tr -d ' ')
draft="$DRAFT_DIR/${session_id}.md"

if [ "$lines" -lt 6 ]; then
  echo "$(date '+%F %T') - SessionEnd: $session_id too short ($lines lines), skipping" >> "$LOG"
  [ -n "$session_id" ] && rm -f "$draft"
  exit 0
fi

draft_note=""
if [ -f "$draft" ]; then
  draft_note="A running draft from this session's Stop hook already exists at: $draft -- read it first as a head start, then verify/expand against the full transcript if needed."
fi

# Precompute everything the model would otherwise need Bash for.
today="$(date '+%Y-%m-%d')"
taxonomy="$(python3 "$HELPERS/list_taxonomy.py" 2>&1)"
recent_sessions="$(ls -1 "$SESSIONS"/*.md 2>/dev/null | xargs -n1 basename 2>/dev/null | sort -r | head -8)"

# The transcript is mostly tool *results* -- a 5-hour session measured 5.1 MB
# across 2529 lines. The model here has `Read` and no Bash, and Read caps at
# 2000 lines with per-line truncation, so pointing it at the raw path meant it
# could never actually read the session: it fell back to the Stop hook's
# 200-word rolling draft and wrote 200-word-shaped summaries of five-hour
# sessions. Digest it here instead (same as taxonomy above) and inline the
# result -- inlining, not a path, because a 150 KB digest sits right on Read's
# truncation boundary and this hook has twice been broken by a tool grant
# behaving differently than assumed.
digest="$(python3 "$HELPERS/transcript_digest.py" "$transcript" 2>/dev/null)"
if [ -n "$digest" ]; then
  digest_block="Below is a digest of the full session -- every user turn and every assistant reply in order, with a one-line trace per tool call (dropping tool output, subagent turns, and thinking). This is your primary source; summarize from it, not from the running draft.

$digest"
else
  digest_block="No digest could be produced; the raw transcript is at $transcript."
fi

echo "$(date '+%F %T') - SessionEnd: invoking claude -p to finalize $session_id" >> "$LOG"

prompt=$(printf '%s\n\n%s\n\n%s\n%s\n\n%s\n%s\n\n%s\n\n%s\n\n%s\n\n%s' \
  "Apply the second-brain skill's \"save session summary\" operation to the Claude Code session that just ended. Read ~/.claude/skills/second-brain/SKILL.md and follow its \"Operation: save session summary\" section exactly, including the skip criteria -- most sessions should NOT get a summary; only genuinely substantial work clears the bar (\"would future-the user want to find this six months from now?\")." \
  "Today's actual local date is $today -- use this exact date for the summary's date: frontmatter and filename. Do NOT use timestamps embedded in the transcript for this; those are UTC and can land a day ahead of local time." \
  "Current real project/topic taxonomy (already looked up for you -- do not guess or invent an ID not listed here):" \
  "$taxonomy" \
  "Filenames already in Claude Archive/Sessions/ (newest first, for checking overlap -- a single conversation can end up split across multiple session IDs, each independently triggering this hook; if one of these already covers essentially the same work as this transcript, SKIP -- do not write a near-duplicate. IMPORTANT: skip means write nothing at all. Never open an existing file and replace or rewrite its content, even a file that looks related -- that silently destroys whatever it covered that this transcript doesn't. If existing coverage is merely incomplete, that's still a reason to skip, not to overwrite; leave it for a human to decide whether to merge. Only ever CREATE a new file at a new path, or write nothing.):" \
  "$recent_sessions" \
  "$draft_note" \
  "$digest_block" \
  "Write for future-the user six months out, and match the length of the session: a five-hour session earns a thorough note, not a headline list. Name the real artifacts -- file paths, type and function names, commands, commit subjects -- the tool traces above give you these, so do not settle for \"the stats service was consolidated\". Preserve the reasoning: what was tried and rejected and why, the constraint behind each decision, the bugs found and their root cause. Skip only what is genuinely ephemeral. If the session clears the bar and nothing above already covers it: use exactly one of project: or topic: in the frontmatter (never both, never invented), and write the summary to $SESSIONS/. You have no Bash access in this call -- do not attempt to run any command; just use your file-writing tool directly. If the session doesn't clear the bar, do nothing." \
  "When you finish, your FINAL line must be exactly one of:
WROTE: <the full absolute path you wrote>
SKIPPED: <one-line reason>
No other text after that line.")

# `env -u ANTHROPIC_API_KEY`: credential precedence is API key BEFORE OAuth,
# and Claude Code injects a key into its own env which children inherit --
# so without this, hook calls bill pay-per-token API credits even when
# logged into a subscription. `--strict-mcp-config` drops MCP server
# definitions this call never uses. Deliberately NOT touching --allowedTools
# or adding --tools here: this hook's tool permissions are load-bearing (see
# the design note at the top) and have broken twice before.
response=$(SECOND_BRAIN_HOOK=1 env -u ANTHROPIC_API_KEY "$CLAUDE_BIN" -p "$prompt" \
  --model claude-sonnet-5 \
  --add-dir "$VAULT" \
  --permission-mode acceptEdits \
  --allowedTools "Read" \
  --strict-mcp-config \
  2>&1)

echo "$response" >> "$LOG"

outcome_line=$(echo "$response" | grep -E '^(WROTE|SKIPPED):' | tail -1)

if [[ "$outcome_line" == WROTE:* ]]; then
  written_path="$(echo "${outcome_line#WROTE:}" | xargs)"
  if [ -f "$written_path" ]; then
    validation_output=$(python3 "$VALIDATE_PY" "$written_path" 2>&1)
    if echo "$validation_output" | grep -q "ERRORS:"; then
      echo "$(date '+%F %T') - SessionEnd: validation failed for $written_path, attempting one fix" >> "$LOG"
      echo "$validation_output" >> "$LOG"
      fix_prompt="The summary you just wrote at $written_path failed validation:

$validation_output

Fix the frontmatter/content in that exact file to address these specific errors (you have no Bash access, use your file-editing tool directly). Reply with only: WROTE: $written_path"
      fix_response=$(SECOND_BRAIN_HOOK=1 env -u ANTHROPIC_API_KEY "$CLAUDE_BIN" -p "$fix_prompt" \
        --model claude-haiku-4-5-20251001 \
        --add-dir "$VAULT" \
        --permission-mode acceptEdits \
        --allowedTools "Read" \
        --strict-mcp-config \
        2>&1)
      echo "$fix_response" >> "$LOG"
      validation_output2=$(python3 "$VALIDATE_PY" "$written_path" 2>&1)
      if echo "$validation_output2" | grep -q "ERRORS:"; then
        echo "$(date '+%F %T') - SessionEnd: still invalid after fix attempt, removing: $written_path" >> "$LOG"
        echo "$validation_output2" >> "$LOG"
        rm -f "$written_path"
      else
        echo "$(date '+%F %T') - SessionEnd: validation passed after fix: $written_path" >> "$LOG"
      fi
    else
      echo "$(date '+%F %T') - SessionEnd: validation passed: $written_path" >> "$LOG"
    fi
  else
    echo "$(date '+%F %T') - SessionEnd: model reported WROTE but file not found: $written_path" >> "$LOG"
  fi
else
  echo "$(date '+%F %T') - SessionEnd: no summary written ($outcome_line)" >> "$LOG"
fi

rm -f "$draft"
echo "$(date '+%F %T') - SessionEnd: done for $session_id" >> "$LOG"
exit 0
