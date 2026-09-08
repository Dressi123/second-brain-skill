#!/bin/bash
# Make this clone yours.
#
# The skill was written for one Mac and hardcodes that Mac's paths and its
# owner's name in SKILL.md, the session hooks and the Codex agent card. This
# rewrites all of them to point at you, then scaffolds the vault folders and
# templates the helper scripts assume already exist.
#
#   ./bootstrap.sh                                   # defaults, prompts once
#   ./bootstrap.sh --vault ~/Documents/MyVault       # vault somewhere else
#   ./bootstrap.sh --name "Sam" --yes                # no prompt
#   ./bootstrap.sh --dry-run                         # show, change nothing
#
# Safe to run twice: every rewrite is a substitution of the original author's
# values, so a second run finds nothing left to change.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# What the repo ships with -- the values being replaced.
OLD_SKILL="$HOME/.claude/skills/second-brain"
OLD_CODEX="$HOME/.codex/skills/second-brain"
OLD_CLAUDE_BIN="$HOME/.local/bin/claude"
OLD_VAULT_TAIL="Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault"
OLD_MARK="iCloud~md~obsidian/Documents/MyVault"
OLD_NAME="the user"

VAULT="$HOME/$OLD_VAULT_TAIL"
NAME=""
ASSUME_YES=0
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --vault)   VAULT="${2:?--vault needs a path}"; shift 2 ;;
    --name)    NAME="${2:?--name needs a name}";   shift 2 ;;
    --yes|-y)  ASSUME_YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

VAULT="${VAULT/#\~/$HOME}"
VAULT="${VAULT%/}"
[ -n "$NAME" ] || NAME="$(id -F 2>/dev/null | awk '{print $1}')"
[ -n "$NAME" ] || NAME="$USER"

# The PreToolUse hook decides whether a tool call touches the vault by
# substring-matching its path. Relative-to-home is the shortest string that
# still only matches this vault.
case "$VAULT" in
  "$HOME"/*) MARK="${VAULT#"$HOME"/}" ;;
  *)         MARK="$VAULT" ;;
esac

CLAUDE_BIN="$(command -v claude || true)"
[ -n "$CLAUDE_BIN" ] || CLAUDE_BIN="$HOME/.local/bin/claude"

cat <<EOF

  skill directory   $SKILL_DIR
  vault             $VAULT
  your name         $NAME
  claude binary     $CLAUDE_BIN

EOF

if [ "$DRY_RUN" = 0 ] && [ "$ASSUME_YES" = 0 ]; then
  read -r -p "Rewrite the skill to use these? [y/N] " reply
  case "$reply" in y|Y|yes|Yes) ;; *) echo "nothing changed."; exit 0 ;; esac
fi

run() { if [ "$DRY_RUN" = 1 ]; then echo "  would: $*"; else "$@"; fi; }

# ---------------------------------------------------------------- 1. rewrite

# `|` as the sed delimiter: every value here is a path full of slashes.
rewrite() {
  local file="$1"
  [ -f "$file" ] || return 0
  if [ "$DRY_RUN" = 1 ]; then echo "  would rewrite: ${file#"$SKILL_DIR"/}"; return 0; fi
  sed -i '' \
    -e "s|$OLD_CLAUDE_BIN|$CLAUDE_BIN|g" \
    -e "s|\$HOME/$OLD_VAULT_TAIL|$VAULT|g" \
    -e "s|~/$OLD_VAULT_TAIL|$VAULT|g" \
    -e "s|$HOME/$OLD_VAULT_TAIL|$VAULT|g" \
    -e "s|$OLD_SKILL|$SKILL_DIR|g" \
    -e "s|$OLD_CODEX|$HOME/.codex/skills/second-brain|g" \
    -e "s|$OLD_MARK|$MARK|g" \
    -e "s|$OLD_NAME|$NAME|g" \
    "$file"
  echo "  rewrote: ${file#"$SKILL_DIR"/}"
}

# helpers/vault_paths.py is the one place every Python helper AND the local
# MCP server get the vault path from, and it composes the original author's
# iCloud path piece by piece rather than as one string -- so it needs its own
# rewrite rather than a substitution.
set_default_vault() {
  local file="$SKILL_DIR/helpers/vault_paths.py"
  if [ "$DRY_RUN" = 1 ]; then echo "  would point helpers/vault_paths.py at the vault"; return 0; fi
  VAULT="$VAULT" python3 - "$file" <<'PY'
import os, re, sys
path = sys.argv[1]
src = open(path).read()
new = 'DEFAULT_VAULT = Path(%r)\n' % os.environ["VAULT"]
# Replace the multi-line Path(...) composition, or an earlier run's one-liner.
src, n = re.subn(r'DEFAULT_VAULT = \((?:.|\n)*?\n\)\n|DEFAULT_VAULT = Path\(.*\)\n', new, src, count=1)
if n != 1:
    sys.exit("could not find DEFAULT_VAULT in %s -- set it by hand" % path)
open(path, "w").write(src)
PY
  echo "  rewrote: helpers/vault_paths.py (DEFAULT_VAULT)"
}

echo "Rewriting paths and name:"
set_default_vault
rewrite "$SKILL_DIR/SKILL.md"
rewrite "$SKILL_DIR/agents/openai.yaml"
for f in "$SKILL_DIR"/helpers/*.sh "$SKILL_DIR"/helpers/new_hub.py; do rewrite "$f"; done
# Both MCP servers put the owner's name in the `instructions` string every
# client displays, so this is not cosmetic -- Claude Desktop and Claude on iOS
# read it on connect.
rewrite "$SKILL_DIR/mcp-server/server.py"
rewrite "$SKILL_DIR/vercel/app.py"
rewrite "$SKILL_DIR/vercel/oauth_stateless.py"
run chmod +x "$SKILL_DIR"/helpers/*.sh "$SKILL_DIR"/vercel/sync_helpers.sh

# mcp-server/vault_tools.py finds the helpers at ~/.claude/skills/second-brain
# unless told otherwise, so a clone anywhere else needs one env var.
if [ "$SKILL_DIR" != "$HOME/.claude/skills/second-brain" ]; then
  echo
  echo "  NOTE: this clone is not at ~/.claude/skills/second-brain."
  echo "  For the MCP servers, export SECOND_BRAIN_HELPERS=$SKILL_DIR/helpers"
fi

# --------------------------------------------------------------- 2. scaffold

echo
echo "Scaffolding the vault:"
for d in "Projects" "Notes/Topics" "Claude Archive/Sessions" "Claude Archive/Bulk export" \
         "Templates" "Inbox" "Daily"; do
  if [ -d "$VAULT/$d" ]; then
    echo "  exists: $d/"
  else
    run mkdir -p "$VAULT/$d"
    echo "  created: $d/"
  fi
done

# The helpers read `Templates/Claude Session Summary.md` by name, so that one
# is not decoration. The other two are the Obsidian templates that go with it.
write_template() {
  local path="$VAULT/Templates/$1.md"
  if [ -e "$path" ]; then echo "  exists: Templates/$1.md"; return 0; fi
  if [ "$DRY_RUN" = 1 ]; then echo "  would create: Templates/$1.md"; return 0; fi
  cat > "$path"
  echo "  created: Templates/$1.md"
}

write_template "Claude Session Summary" <<'EOF'
---
date: {{date}}
topic:
project:
tags: [claude-session]
---

# {{title}}

## Topic
<!-- One sentence: what was this conversation about? -->

## What we figured out
<!-- The actual takeaways. Decisions, conclusions, working answers. -->

## Code / artifacts
<!-- Snippets, commands, links to files Claude created. -->

## Open questions / next steps
- [ ]

## Context for next time
<!-- What does future-Claude need to know to pick this up cold? -->

## Reference
<!-- Link to original chat if available, or paste key excerpts. -->
EOF

write_template "Project" <<'EOF'
---
status: active
created: {{date}}
tags: [project]
---

# {{title}}

## Goal
<!-- One sentence. What does "done" look like? -->

## Status
<!-- Where are we right now? -->

## Key decisions
-

## Notes


## Open questions
-

## Linked
- <!-- wikilinks to related session summaries / notes go here -->
EOF

write_template "Daily Note" <<'EOF'
---
date: {{date}}
tags: [daily]
---

# {{date:dddd, MMMM D, YYYY}}

## Today's focus


## Notes & thinking


## Open threads
- [ ]

## Tomorrow
-

## Worth saving
<!-- Anything from today worth promoting to a Project, Note, or Claude Archive entry -->
EOF

# ----------------------------------------------------------------- 3. verify

echo
if [ "$DRY_RUN" = 1 ]; then
  echo "Dry run -- nothing was written."
  exit 0
fi

# Skipped when you ARE the original author (testing on that Mac), where the
# rewritten values are byte-identical to the originals and every hit is false.
leftovers=""
if [ "$HOME" != "$HOME" ]; then
  leftovers=$(grep -rln "$HOME\|$OLD_MARK" \
    "$SKILL_DIR/SKILL.md" "$SKILL_DIR/agents" "$SKILL_DIR"/helpers/*.sh \
    "$SKILL_DIR"/helpers/*.py 2>/dev/null || true)
fi
if [ -n "$leftovers" ]; then
  echo "WARNING -- the original author's paths still appear in:"
  printf '  %s\n' $leftovers
  echo "Open those and fix them by hand before relying on the skill."
else
  echo "No hardcoded paths from the original author remain."
fi

echo
echo "Smoke test:"
python3 "$SKILL_DIR/helpers/vault_index.py" | head -3 || true

cat <<EOF

Done. The skill works now -- ask Claude Code "what's in my second brain?".

To make it automatic, add the hooks to ~/.claude/settings.json (Tier 2 in the
README). The block for YOUR paths:

  "permissions": {
    "additionalDirectories": ["$VAULT"]
  },
  "hooks": {
    "PreToolUse": [{ "matcher": "Read|Write|Edit|Bash", "hooks": [{ "type": "command",
      "command": "bash $SKILL_DIR/helpers/vault_pretool_pull_hook.sh",
      "timeout": 20, "statusMessage": "Syncing second-brain vault..." }] }],
    "SessionStart": [{ "hooks": [{ "type": "command",
      "command": "bash $SKILL_DIR/helpers/session_start_inbox_check.sh",
      "timeout": 15, "statusMessage": "Checking second-brain inbox..." }] }],
    "Stop": [{ "hooks": [{ "type": "command",
      "command": "bash $SKILL_DIR/helpers/session_stop_draft_hook.sh",
      "timeout": 120, "async": true, "statusMessage": "Updating second-brain draft..." }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command",
      "command": "bash $SKILL_DIR/helpers/session_end_finalize_hook.sh",
      "timeout": 900, "async": true, "statusMessage": "Saving session to second brain..." }] }]
  }

EOF
