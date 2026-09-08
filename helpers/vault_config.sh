# Sourced by the shell hooks to learn where the vault is.
#
# The path used to be a literal string in each script, which meant every clone
# carried its author's home directory and had to be rewritten before it worked.
# It now comes from .bootstrap.conf, which bootstrap.sh writes and git ignores
# -- so the tracked files stay generic and a set-up clone has a clean tree.
#
#   . "$(dirname "${BASH_SOURCE[0]}")/vault_config.sh"   # sets VAULT
#
# Precedence matches helpers/vault_paths.py: $SECOND_BRAIN_VAULT wins, then
# .bootstrap.conf, then the default iCloud Obsidian location.

_vc_helpers="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_vc_conf="$(dirname "$_vc_helpers")/.bootstrap.conf"

if [ -n "${SECOND_BRAIN_VAULT:-}" ]; then
  VAULT="$SECOND_BRAIN_VAULT"
elif [ -f "$_vc_conf" ]; then
  # shellcheck disable=SC1090
  . "$_vc_conf"
  VAULT="${CONF_VAULT:-}"
fi
[ -n "${VAULT:-}" ] || \
  VAULT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault"

unset _vc_helpers _vc_conf
