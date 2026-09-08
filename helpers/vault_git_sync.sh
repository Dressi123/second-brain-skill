#!/bin/bash
# Keep the iCloud vault on this Mac and its GitHub mirror in step. The mirror
# is what the hosted MCP server (Claude on iPhone/web) reads and writes, so
# this is the bridge between "the vault on my Mac" and "the vault on my phone".
#
# Deliberately NOT a launchd timer: macOS denies background agents access to
# ~/Library/Mobile Documents, so a timer gets "Operation not permitted" on
# every file unless bash is granted Full Disk Access by hand. Instead this is
# called from processes that already have vault access -- Claude Code's
# session hooks and the local MCP server.
#
#   vault_git_sync.sh pull [--force]   take remote work, skipped if fresh
#   vault_git_sync.sh push             commit local work and publish it
#   vault_git_sync.sh sync             pull then push
#
# Always exits 0 on network trouble: being offline must never break a vault
# read or fail a hook. A genuine conflict exits 1 and says so.
set -uo pipefail

VAULT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault"
GIT_DIR="$HOME/.second-brain-git"
LOG="$GIT_DIR/sync.log"
LOCK="$GIT_DIR/sync.lock.d"
STAMP="$GIT_DIR/last-pull"
# 0 = always fetch before a read. Every vault read on this Mac goes through
# a pull so nothing captured on the phone is ever missed. Set this to a
# number of seconds only if the round trip ever becomes a nuisance.
FRESH_SECS="${VAULT_SYNC_FRESH_SECS:-0}"

# Bound every network call: a hook must not hang a session on a dead network.
export GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=10
export GIT_TERMINAL_PROMPT=0

git() { command git --git-dir="$GIT_DIR" --work-tree="$VAULT" "$@"; }
log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

[ -d "$VAULT" ] && [ -d "$GIT_DIR" ] || { log "ERROR vault or git dir missing"; exit 0; }
cd "$VAULT" || exit 0

# Never touch a repo left mid-operation; a human needs to look at it.
if [ -d "$GIT_DIR/rebase-merge" ] || [ -d "$GIT_DIR/rebase-apply" ] || [ -f "$GIT_DIR/MERGE_HEAD" ]; then
  log "STOP repo is mid-rebase/merge -- resolve by hand, sync paused"
  echo "second-brain: vault repo is mid-rebase, sync paused. Resolve in $VAULT" >&2
  exit 1
fi

# Single instance; mkdir is atomic and macOS has no flock(1).
mkdir "$LOCK" 2>/dev/null || {
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
    log "WARN clearing stale lock"; rmdir "$LOCK" 2>/dev/null; mkdir "$LOCK" 2>/dev/null || exit 0
  else
    exit 0   # another pull/push is already in flight; nothing to do
  fi
}
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

has_remote() { git remote get-url origin >/dev/null 2>&1; }
branch() { git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main; }

do_pull() {
  local force="${1:-}"
  has_remote || return 0

  # Optional throttle, off by default (FRESH_SECS=0 means always fetch).
  if [ -z "$force" ] && [ "$FRESH_SECS" -gt 0 ] && [ -f "$STAMP" ]; then
    local age=$(( $(date +%s) - $(stat -f %m "$STAMP" 2>/dev/null || echo 0) ))
    [ "$age" -lt "$FRESH_SECS" ] && return 0
  fi

  git fetch --quiet origin 2>>"$LOG" || { log "WARN fetch failed (offline?)"; return 0; }
  touch "$STAMP"

  local b; b=$(branch)
  git rev-parse --quiet --verify "origin/$b" >/dev/null || return 0
  local behind; behind=$(git rev-list --count "HEAD..origin/$b")
  [ "$behind" -gt 0 ] || return 0

  # Stash anything uncommitted so a rebase can never eat in-progress edits.
  local stashed=""
  if [ -n "$(git status --porcelain)" ]; then
    git stash push --quiet --include-untracked -m "vault-sync autostash" 2>>"$LOG" && stashed=1
  fi

  if git rebase --quiet "origin/$b" 2>>"$LOG"; then
    log "pulled $behind commit(s) from GitHub"
  else
    git rebase --abort 2>/dev/null
    [ -n "$stashed" ] && git stash pop --quiet 2>>"$LOG"
    log "STOP rebase conflicted and was aborted -- same file edited here and on the phone. Nothing lost; resolve by hand."
    echo "second-brain: vault sync conflict, resolve in $VAULT" >&2
    return 1
  fi
  [ -n "$stashed" ] && git stash pop --quiet 2>>"$LOG"
  return 0
}

do_push() {
  if [ -n "$(git status --porcelain)" ]; then
    git add -A 2>>"$LOG"
    local count; count=$(git diff --cached --name-only | wc -l | tr -d ' ')
    if [ "$count" -gt 0 ]; then
      # Identity from this machine's git config, not baked in here: a
      # hardcoded author leaks an email in a shared clone and signs someone
      # else's vault commits with it.
      local gname gemail
      gname=$(git config --global user.name 2>/dev/null); [ -n "$gname" ] || gname="second-brain"
      gemail=$(git config --global user.email 2>/dev/null); [ -n "$gemail" ] || gemail="second-brain@localhost"
      git -c user.name="$gname" -c user.email="$gemail" \
          commit -q -m "vault: $count file(s) changed on Mac ($(date '+%Y-%m-%d %H:%M'))" 2>>"$LOG" \
        && log "committed $count local change(s)"
    fi
  fi

  has_remote || return 0
  local b; b=$(branch)
  git rev-parse --quiet --verify "origin/$b" >/dev/null || { git push --quiet -u origin "$b" 2>>"$LOG"; return 0; }

  local ahead; ahead=$(git rev-list --count "origin/$b..HEAD" 2>/dev/null || echo 0)
  [ "$ahead" -gt 0 ] || return 0
  if git push --quiet origin "$b" 2>>"$LOG"; then
    log "pushed $ahead commit(s)"
  else
    # Remote moved under us: take its work, then try once more.
    do_pull --force || return 1
    git push --quiet origin "$b" 2>>"$LOG" && log "pushed after rebase" || log "WARN push failed, will retry next time"
  fi
  return 0
}

case "${1:-sync}" in
  pull) do_pull "${2:-}" ;;
  push) do_push ;;
  sync) do_pull "${2:-}" && do_push ;;
  *) echo "usage: $0 {pull|push|sync} [--force]" >&2; exit 2 ;;
esac
