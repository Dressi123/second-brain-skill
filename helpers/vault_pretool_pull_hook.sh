#!/bin/bash
# PreToolUse: keep the vault in step with its GitHub mirror around every
# Claude Code read or write of it, so a note captured on the iPhone is never
# missed and a note written here reaches the phone.
#
#   Read / Bash  -> pull   (one round trip, take remote work)
#   Write / Edit -> sync   (pull, then commit and push what we just wrote)
#
# Doing the push here rather than only in the session hooks matters: those
# are async and have several early-exit paths, so a summary written late in
# a session could sit unpushed. Converging on the next vault touch does not
# depend on any of that.
#
# Fires on every Read/Write/Edit/Bash call, so it first decides whether this
# call touches the vault at all -- almost always it does not, and then it
# exits before touching the network.
set -uo pipefail

_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_here/vault_config.sh"   # sets VAULT

# Match on the vault path relative to home -- the shortest string that still
# only matches this vault, and one that carries no home directory of its own.
VAULT_MARK="${VAULT#"$HOME"/}"
HELPERS_MARK="skills/second-brain/helpers"
SYNC="$_here/vault_git_sync.sh"

payload=$(cat)
[ -x "$SYNC" ] || exit 0

# Match the path or command only, never the whole payload: a Write or Edit
# carries file CONTENT too, and a source file that merely mentions the vault
# path in a comment should not cost a network fetch.
target=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // .tool_input.command // ""' 2>/dev/null)
tool=$(printf '%s' "$payload" | jq -r '.tool_name // ""' 2>/dev/null)

case "$target" in
  *"$VAULT_MARK"*|*"$HELPERS_MARK"*) ;;
  *) exit 0 ;;
esac

case "$tool" in
  Write|Edit) "$SYNC" sync >/dev/null 2>&1 ;;
  *)          "$SYNC" pull >/dev/null 2>&1 ;;
esac
exit 0   # never block the tool call: a sync problem must not stop the work
