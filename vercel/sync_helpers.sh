#!/bin/bash
# Copy the vault code this deployment needs out of the skill directory.
#
# Vendored rather than shared, because Vercel deploys one directory and this
# one must stay small and explicit about what it ships.
# Re-run after changing any helper, then redeploy.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$DEST/helpers"
for f in vault_paths.py vault_index.py search_notes.py list_taxonomy.py; do
  cp "$SRC/helpers/$f" "$DEST/helpers/$f"
  echo "  helpers/$f"
done
cp "$SRC/mcp-server/vault_tools.py" "$DEST/vault_tools.py"
echo "  vault_tools.py"
echo "synced from $SRC"
