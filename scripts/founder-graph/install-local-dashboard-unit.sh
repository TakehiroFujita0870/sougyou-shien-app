#!/usr/bin/env bash
# Install only the fixed, loopback-bound controller definition. This script
# deliberately does not start or enable the unit or touch live data services.
set -Eeuo pipefail

[[ $# -eq 3 ]] || { printf '%s\n' 'Usage: install-local-dashboard-unit.sh <repository> <control-plane-env-file> <neo4j-auth-file>' >&2; exit 2; }
repo="$1"
control_env="$2"
auth_file="$3"
unit_name='nebula-local-dashboard.service'
source_unit="$repo/scripts/founder-graph/$unit_name"
unit_directory="$HOME/.config/systemd/user"
unit_target="$unit_directory/$unit_name"
expected_repo="$HOME/projects/nebula-live"
candidate=''
installed_by_this_run=0

fail() { printf '[nebula local dashboard installer] %s\n' "$1" >&2; exit 1; }
cleanup() {
  local result=$?
  if [[ -n "$candidate" && -f "$candidate" ]]; then rm -f -- "$candidate"; fi
  if [[ $result -ne 0 && $installed_by_this_run -eq 1 ]]; then
    rm -f -- "$unit_target"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  exit "$result"
}
trap cleanup EXIT

assert_private_file() {
  local path="$1"
  [[ -f "$path" && ! -L "$path" ]] || fail 'A required live configuration file is unavailable.'
  [[ "$(stat -c '%u:%a' -- "$path")" == "$(id -u):600" ]] || fail 'A required live configuration file is not owner-only.'
}

assert_control_env() {
  local exact_target="$HOME/.config/nebula/live-runtime-key.env"
  if [[ -L "$control_env" ]]; then
    [[ "$(readlink -- "$control_env")" == "$exact_target" ]] || fail 'The control-plane link points outside its approved target.'
    [[ "$(stat -c '%u' -- "$control_env")" == "$(id -u)" ]] || fail 'The control-plane link has a different owner.'
    assert_private_file "$exact_target"
  else
    assert_private_file "$control_env"
  fi
}

[[ "$HOME" == /* && -d "$HOME" && ! -L "$HOME" && "$(realpath -e -- "$HOME")" == "$HOME" ]] || fail 'The current user home path is unsafe.'
[[ "$repo" == "$expected_repo" && -d "$repo" && ! -L "$repo" ]] || fail 'The repository path does not match the approved live checkout.'
[[ "$control_env" == "$HOME/.config/nebula/live-control-plane.env" ]] || fail 'The control-plane file path did not match.'
[[ "$auth_file" == "$HOME/.config/nebula/live-neo4j-auth.secret" ]] || fail 'The auth-file path did not match.'
assert_control_env
assert_private_file "$auth_file"
[[ -f "$source_unit" && ! -L "$source_unit" ]] || fail 'The controller unit source is unavailable.'
[[ -f "$repo/dist/index.html" && ! -L "$repo/dist/index.html" ]] || fail 'The built dashboard is unavailable.'
grep -Fqx 'Environment=NEBULA_LOCAL_OWNER_ID=owner-mvp' "$source_unit" || fail 'The owner target did not match.'
grep -Fqx 'ExecStart=%h/.local/bin/uv run --project %h/projects/nebula-live uvicorn --app-dir backend nebula.local_dashboard_runtime:app --host 127.0.0.1 --port 8765' "$source_unit" || fail 'The controller listener did not match.'

for directory in "$HOME/.config" "$HOME/.config/systemd" "$unit_directory"; do
  [[ ! -L "$directory" && ( ! -e "$directory" || -d "$directory" ) ]] || fail 'A user unit directory is unsafe.'
done
mkdir -p -- "$unit_directory"
[[ "$(realpath -e -- "$unit_directory")" == "$unit_directory" && "$(stat -c '%u' -- "$unit_directory")" == "$(id -u)" ]] || fail 'The user unit directory is not owned by the current user.'

candidate="$(mktemp "$unit_directory/.nebula-local-dashboard.service.XXXXXX")" || fail 'A candidate unit could not be created.'
install -m 0644 -- "$source_unit" "$candidate"
if [[ -e "$unit_target" || -L "$unit_target" ]]; then
  [[ -f "$unit_target" && ! -L "$unit_target" ]] || fail 'An existing controller unit is not a regular file.'
  cmp -s -- "$candidate" "$unit_target" || fail 'An existing controller unit differs and was not overwritten.'
else
  install -m 0644 -- "$candidate" "$unit_target" || fail 'The controller unit could not be installed.'
  installed_by_this_run=1
fi
cmp -s -- "$candidate" "$unit_target" || fail 'Controller unit read-back failed.'
systemctl --user daemon-reload || fail 'The user service manager could not reload the definition.'
installed_by_this_run=0
printf '%s\n' '[nebula local dashboard installer] Fixed controller unit installed; it was not started or enabled.'
