#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  printf '%s\n' 'Usage: install-live-api-unit.sh --confirm-credential-rotation --confirm-private-projection-review <repository> <control-plane-env-file> <neo4j-auth-file>' >&2
  exit 2
}

[[ $# -eq 5 ]] || usage
[[ "$1" == '--confirm-credential-rotation' ]] || usage
[[ "$2" == '--confirm-private-projection-review' ]] || usage
repo="$3"
control_env="$4"
auth_file="$5"
unit_name='dots-live-api.service'
unit_source="$repo/scripts/founder-graph/$unit_name"
unit_directory="$HOME/.config/systemd/user"
unit_target="$unit_directory/$unit_name"
expected_repo="$HOME/projects/dots-live"
expected_control_env="$HOME/.config/dots/live-control-plane.env"
expected_auth_file="$HOME/.config/dots/live-neo4j-auth.secret"
candidate=''
installed_by_this_run=0

fail() { printf '[dots live API installer] %s\n' "$1" >&2; exit 1; }
cleanup() {
  local exit_status=$?
  if [[ -n "$candidate" && -f "$candidate" ]]; then rm -f -- "$candidate"; fi
  if [[ $exit_status -ne 0 && $installed_by_this_run -eq 1 ]]; then
    rm -f -- "$unit_target"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  exit "$exit_status"
}
trap cleanup EXIT

assert_owner_only_file() {
  local file="$1" actual expected
  [[ -f "$file" && ! -L "$file" ]] || fail 'A required live configuration file is unavailable or not regular.'
  actual="$(stat -c '%u:%a' -- "$file")" || fail 'Live file metadata could not be checked.'
  expected="$(id -u):600"
  [[ "$actual" == "$expected" ]] || fail 'A required live configuration file is not current-user-owned mode 0600.'
}

assert_control_env_file() {
  local file="$1" expected_target resolved_target
  if [[ -L "$file" ]]; then
    # Accept only the exact absolute target or its exact adjacent relative form.
    [[ "$(readlink -- "$file")" == "$HOME/.config/dots/live-runtime-key.env" || \
       "$(readlink -- "$file")" == 'live-runtime-key.env' ]] || \
      fail 'The control-plane link must target the approved same-directory runtime env file.'
    [[ ! -L "$HOME/.config" && ! -L "$HOME/.config/dots" && -d "$HOME/.config/dots" ]] || \
      fail 'The control-plane directory path must not contain symlinks.'
    expected_target="$HOME/.config/dots/live-runtime-key.env"
    [[ -f "$expected_target" && ! -L "$expected_target" ]] || \
      fail 'The approved runtime env target is unavailable or not a regular file.'
    resolved_target="$(realpath -e -- "$file")" || fail 'The control-plane target could not be resolved.'
    [[ "$(realpath -e -- "$HOME/.config/dots")" == "$HOME/.config/dots" && \
       "$resolved_target" == "$expected_target" ]] || \
      fail 'The control-plane link did not resolve to the exact same-directory target.'
    assert_owner_only_file "$expected_target"
  else
    assert_owner_only_file "$file"
  fi
}

[[ "$repo" == "$expected_repo" && -d "$repo" && ! -L "$repo" ]] || \
  fail "The repository must be the current user's exact projects/dots-live directory."
[[ "$HOME" == /* && -d "$HOME" && ! -L "$HOME" && "$(realpath -e -- "$HOME")" == "$HOME" ]] || \
  fail 'The current user home path is not a canonical regular directory.'
[[ "$control_env" == "$expected_control_env" ]] || fail 'The control-plane file path does not match the expected user path.'
[[ "$auth_file" == "$expected_auth_file" ]] || fail 'The Neo4j auth-file path does not match the expected user path.'
[[ -f "$unit_source" && ! -L "$unit_source" ]] || fail 'The live API service template is missing or not regular.'
assert_control_env_file "$control_env"
assert_owner_only_file "$auth_file"

for directory in "$HOME/.config" "$HOME/.config/systemd" "$unit_directory"; do
  if [[ -L "$directory" || ( -e "$directory" && ! -d "$directory" ) ]]; then
    fail 'A systemd user configuration path is not a regular directory.'
  fi
done

# The source stays inert. Only this explicit, guarded installer creates the
# approved installed variant, and it first validates the exact gate lines.
[[ "$(grep -Fxc 'Environment=DOTS_LIVE_CREDENTIAL_ROTATION_CONFIRMED=0' "$unit_source")" == 1 ]] || \
  fail 'The API template credential-rotation gate is missing or ambiguous.'
[[ "$(grep -Fxc 'Environment=DOTS_LIVE_EGRESS_REVIEW_CONFIRMED=0' "$unit_source")" == 1 ]] || \
  fail 'The API template private-projection gate is missing or ambiguous.'
grep -Fqx 'Environment=DOTS_LOCAL_OWNER_ID=owner-mvp' "$unit_source" || fail 'The API template owner target did not match.'
grep -Fqx 'ExecStart=%h/.local/bin/uv run --project %h/projects/dots-live uvicorn --app-dir backend dots.main:app --host 127.0.0.1 --port 8000' "$unit_source" || \
  fail 'The API template listener or application target did not match.'

mkdir -p -- "$unit_directory"
[[ ! -L "$unit_directory" && "$(realpath -e -- "$unit_directory")" == "$unit_directory" ]] || \
  fail 'The systemd user unit directory did not resolve to the expected path.'
[[ "$(stat -c '%u' -- "$unit_directory")" == "$(id -u)" ]] || fail 'The systemd user unit directory is not owned by the current user.'
candidate="$(mktemp "$unit_directory/.dots-live-api.service.XXXXXX")" || fail 'A protected candidate unit could not be created.'
chmod 0644 -- "$candidate"
sed \
  -e 's/^Environment=DOTS_LIVE_CREDENTIAL_ROTATION_CONFIRMED=0$/Environment=DOTS_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1/' \
  -e 's/^Environment=DOTS_LIVE_EGRESS_REVIEW_CONFIRMED=0$/Environment=DOTS_LIVE_EGRESS_REVIEW_CONFIRMED=1/' \
  "$unit_source" > "$candidate"
[[ "$(grep -Fxc 'Environment=DOTS_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1' "$candidate")" == 1 ]] || fail 'The installed credential gate did not pass read-back.'
[[ "$(grep -Fxc 'Environment=DOTS_LIVE_EGRESS_REVIEW_CONFIRMED=1' "$candidate")" == 1 ]] || fail 'The installed private-projection gate did not pass read-back.'
grep -Fqx 'Environment=DOTS_LOCAL_OWNER_ID=owner-mvp' "$candidate" || fail 'The installed owner target did not pass read-back.'
grep -Fqx 'ExecStart=%h/.local/bin/uv run --project %h/projects/dots-live uvicorn --app-dir backend dots.main:app --host 127.0.0.1 --port 8000' "$candidate" || \
  fail 'The installed API listener did not pass read-back.'

if [[ -e "$unit_target" || -L "$unit_target" ]]; then
  [[ -f "$unit_target" && ! -L "$unit_target" ]] || fail 'The existing live API unit is not a regular file.'
  cmp -s -- "$candidate" "$unit_target" || fail 'The existing live API unit differs and was not overwritten.'
else
  install -m 0644 -- "$candidate" "$unit_target" || fail 'The validated API unit could not be installed.'
  installed_by_this_run=1
fi
cmp -s -- "$candidate" "$unit_target" || fail 'Installed API unit read-back failed; the new file will be rolled back.'

# Definition reload only: never enable or start the API service here.
systemctl --user daemon-reload || fail 'Systemd could not reload unit definitions; the new file will be rolled back.'
installed_by_this_run=0
printf '%s\n' '[dots live API installer] Approved API unit installed; it was not enabled or started.'
