#!/bin/bash
# Copy the vault code this deployment needs out of the skill directory.
#
# Vendored rather than shared, because Vercel deploys one directory and this
# one must stay small: the skill directory next door holds .oauth_password
# and .remote_token, and a gitignore slip there would publish a credential.
# Re-run after changing any helper, then redeploy.
set -euo pipefail
SRC="$HOME/.claude/skills/second-brain"
DEST="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$DEST/helpers"
for f in vault_paths.py vault_index.py search_notes.py list_taxonomy.py; do
  cp "$SRC/helpers/$f" "$DEST/helpers/$f"
  echo "  helpers/$f"
done
cp "$SRC/mcp-server/vault_tools.py" "$DEST/vault_tools.py"
echo "  vault_tools.py"
echo "synced from $SRC"
