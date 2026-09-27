#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 3 ]]; then
  printf '%s\n' 'Usage: install-live-mcp-tunnel-unit.sh <repository> <control-plane-env-file> <neo4j-auth-file>' >&2
  exit 2
fi

repo="$1"
control_env="$2"
auth_file="$3"
unit_source="$repo/scripts/founder-graph/dots-live-mcp-tunnel.service"
unit_directory="$HOME/.config/systemd/user"
unit_target="$unit_directory/dots-live-mcp-tunnel.service"
env_link="$HOME/.config/dots/live-control-plane.env"
expected_auth_file="$HOME/.config/dots/live-neo4j-auth.secret"

fail() { printf '[dots live unit installer] %s\n' "$1" >&2; exit 1; }
assert_owner_only_file() {
  local file="$1" expected_owner expected_mode actual
  [[ -f "$file" && ! -L "$file" ]] || fail 'A required live configuration file is unavailable or not regular.'
  expected_owner="$(id -u)"
  actual="$(stat -c '%u:%a' -- "$file")" || fail 'Live file metadata could not be checked.'
  expected_mode="$expected_owner:600"
  [[ "$actual" == "$expected_mode" ]] || fail 'A required live configuration file is not owner-only mode 0600.'
}

[[ -f "$unit_source" && ! -L "$unit_source" ]] || fail 'The live service template is missing or not regular.'
[[ "$repo" == /* && "$control_env" == /* ]] || fail 'The repository and control-plane file paths must be absolute.'
[[ "$auth_file" == "$expected_auth_file" ]] || fail 'The Neo4j auth-file path does not match the live service template.'
assert_owner_only_file "$control_env"
assert_owner_only_file "$auth_file"

mkdir -p "$HOME/.config/dots" "$unit_directory"
if [[ -L "$env_link" ]]; then
  [[ "$(readlink -- "$env_link")" == "$control_env" ]] || fail 'The existing live control-plane link points elsewhere.'
elif [[ -e "$env_link" ]]; then
  fail 'The live control-plane path exists and is not the expected link.'
else
  ln -s -- "$control_env" "$env_link"
fi

if [[ -e "$unit_target" ]]; then
  [[ -f "$unit_target" && ! -L "$unit_target" ]] || fail 'The existing live systemd unit is not a regular file.'
  cmp -s -- "$unit_source" "$unit_target" || fail 'The existing live systemd unit differs and was not overwritten.'
else
  install -m 0644 -- "$unit_source" "$unit_target"
fi

# Reload definitions only. This does not start or enable the external tunnel.
systemctl --user daemon-reload
printf '%s\n' '[dots live unit installer] Dormant live unit is installed; activation flags remain controlled by the unit.'
