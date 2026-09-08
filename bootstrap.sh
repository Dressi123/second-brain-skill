#!/bin/bash
# Point this clone at your vault.
#
# Writes .bootstrap.conf (gitignored) with the vault path, then creates the
# folders and templates the helper scripts expect to find. Nothing tracked is
# modified, so `git status` stays clean and `git pull` keeps working.
#
#   ./bootstrap.sh                                   # defaults, prompts once
#   ./bootstrap.sh --vault ~/Documents/MyVault       # vault somewhere else
#   ./bootstrap.sh --yes                             # no prompt
#   ./bootstrap.sh --dry-run                         # show, change nothing
#
# Safe to run again at any time: it rewrites the config and skips anything in
# the vault that already exists.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$SKILL_DIR/.bootstrap.conf"
DEFAULT_VAULT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault"

VAULT=""
ASSUME_YES=0
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --vault)   VAULT="${2:?--vault needs a path}"; shift 2 ;;
    --yes|-y)  ASSUME_YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# Reuse last run's answer, so a re-run after a pull needs no flags.
if [ -z "$VAULT" ] && [ -f "$CONF" ]; then
  # shellcheck disable=SC1090
  . "$CONF"; VAULT="${CONF_VAULT:-}"
fi
[ -n "$VAULT" ] || VAULT="$DEFAULT_VAULT"
VAULT="${VAULT/#\~/$HOME}"
VAULT="${VAULT%/}"

cat <<EOF

  skill directory   $SKILL_DIR
  vault             $VAULT

EOF

if [ "$DRY_RUN" = 0 ] && [ "$ASSUME_YES" = 0 ]; then
  read -r -p "Use this vault? [y/N] " reply
  case "$reply" in y|Y|yes|Yes) ;; *) echo "nothing changed."; exit 0 ;; esac
fi

run() { if [ "$DRY_RUN" = 1 ]; then echo "  would: $*"; else "$@"; fi; }

# ------------------------------------------------------------------ config

if [ "$DRY_RUN" = 1 ]; then
  echo "  would write $CONF"
else
  printf 'CONF_VAULT=%q\n' "$VAULT" > "$CONF"
  echo "Wrote .bootstrap.conf (gitignored) — every helper reads the vault path from here."
fi
# Not vault_config.sh -- it is sourced, never executed, and marking it +x
# shows the clone as modified for a mode bit it does not want.
for _s in "$SKILL_DIR"/helpers/*.sh; do
  case "$_s" in *_hook.sh|*vault_git_sync.sh) run chmod +x "$_s" ;; esac
done
run chmod +x "$SKILL_DIR/vercel/sync_helpers.sh"

# mcp-server/vault_tools.py looks for the helpers at the default install path
# unless told otherwise, so a clone anywhere else needs one env var.
if [ "$SKILL_DIR" != "$HOME/.claude/skills/second-brain" ]; then
  echo
  echo "  NOTE: this clone is not at ~/.claude/skills/second-brain."
  echo "  For the MCP servers, export SECOND_BRAIN_HELPERS=$SKILL_DIR/helpers"
fi

# ---------------------------------------------------------------- scaffold

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
  if [ -e "$path" ]; then echo "  exists: Templates/$1.md"; cat > /dev/null; return 0; fi
  if [ "$DRY_RUN" = 1 ]; then echo "  would create: Templates/$1.md"; cat > /dev/null; return 0; fi
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
<!-- What does future-you need to know to pick this up cold? -->

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

# ------------------------------------------------------------------ verify

echo
if [ "$DRY_RUN" = 1 ]; then
  echo "Dry run -- nothing was written."
  exit 0
fi

resolved=$(python3 "$SKILL_DIR/helpers/vault_paths.py")
if [ "$resolved" != "$VAULT" ]; then
  echo "WARNING -- the helpers resolve the vault to:"
  echo "  $resolved"
  echo "which is not what you asked for. \$SECOND_BRAIN_VAULT in your environment wins"
  echo "over .bootstrap.conf; unset it, or use it consistently."
else
  echo "Helpers agree the vault is $resolved"
fi

echo
echo "Smoke test:"
python3 "$SKILL_DIR/helpers/vault_index.py" | head -3 || true

cat <<EOF

Done. Ask Claude Code "what's in my second brain?".

Two things left, both in the README:
  1. Add the pointer to ~/.claude/CLAUDE.md so Claude reaches for the skill
     unprompted. This is the difference between a skill that fires when you
     name it and one that loads a project's history when you open its repo.
  2. Add the hooks to ~/.claude/settings.json to have sessions save themselves:

  "permissions": {
    "additionalDirectories": ["$VAULT"]
  },
  "hooks": {
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
