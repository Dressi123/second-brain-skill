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

# Optional second vault: a read-only mirror of the main vault, on a machine
# whose own vault is local and unsynced (a work laptop that may not push its
# notes anywhere). Reads may span both; every write still goes to $VAULT.
# Empty on a single-vault machine, which is the normal case.
if [ -n "${SECOND_BRAIN_MIRROR:-}" ]; then
  MIRROR="$SECOND_BRAIN_MIRROR"
elif [ -f "$_vc_conf" ]; then
  # shellcheck disable=SC1090
  . "$_vc_conf"
  MIRROR="${CONF_MIRROR:-}"
fi
[ -d "${MIRROR:-}" ] || MIRROR=""

unset _vc_helpers _vc_conf
