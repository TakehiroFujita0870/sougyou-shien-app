#!/usr/bin/env bash
set -Eeuo pipefail

readonly repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
readonly installer="$repo/scripts/founder-graph/install-live-api-unit.sh"
readonly temp_root="$(mktemp -d)"
trap 'rm -rf -- "$temp_root"' EXIT

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
home="$temp_root/home"
fake_repo="$home/projects/nebula-live"
control_env="$home/.config/nebula/live-control-plane.env"
auth_file="$home/.config/nebula/live-neo4j-auth.secret"
unit_dir="$home/.config/systemd/user"
mkdir -p "$fake_repo/scripts/founder-graph" "$home/.config/nebula" "$temp_root/bin"
cp "$repo/scripts/founder-graph/nebula-live-api.service" "$fake_repo/scripts/founder-graph/"
printf '%s\n' 'fake runtime config, not a credential' > "$home/.config/nebula/live-runtime-key.env"
printf '%s\n' 'fake auth bytes, not a credential' > "$auth_file"
chmod 600 "$home/.config/nebula/live-runtime-key.env" "$auth_file"
ln -s "$home/.config/nebula/live-runtime-key.env" "$control_env"
cp "$repo/scripts/founder-graph/tests/fixtures/fake-systemctl.sh" "$temp_root/bin/systemctl"
chmod +x "$temp_root/bin/systemctl"
export SYSTEMCTL_LOG="$temp_root/systemctl.log"

run_installer() {
  HOME="$home" PATH="$temp_root/bin:$PATH" bash "$installer" "$@"
}
args=(--confirm-credential-rotation --confirm-private-projection-review "$fake_repo" "$control_env" "$auth_file")

# Both explicit approvals are required before any installed unit is written.
set +e
missing_flag_output="$(HOME="$home" PATH="$temp_root/bin:$PATH" bash "$installer" \
  --confirm-credential-rotation "$fake_repo" "$control_env" "$auth_file" 2>&1)"
missing_flag_status=$?
set -e
[[ $missing_flag_status -ne 0 && ! -e "$unit_dir/nebula-live-api.service" ]] || fail 'A missing approval flag installed the API unit.'
[[ ! -e "$SYSTEMCTL_LOG" ]] || fail 'Systemd was touched before both approval flags were supplied.'

run_installer "${args[@]}" >/dev/null || fail 'Valid approvals and owner-only files did not install the unit.'
installed="$unit_dir/nebula-live-api.service"
[[ "$(grep -Fxc 'Environment=NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1' "$installed")" == 1 ]] || fail 'Installed rotation approval gate is not enabled.'
[[ "$(grep -Fxc 'Environment=NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' "$installed")" == 1 ]] || fail 'Installed projection approval gate is not enabled.'
[[ "$(grep -Fxc 'Environment=NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=0' "$fake_repo/scripts/founder-graph/nebula-live-api.service")" == 1 ]] || fail 'The source template was modified.'
[[ "$(<"$SYSTEMCTL_LOG")" == '--user daemon-reload' ]] || fail 'The installer enabled or started the unit.'

# Only the exact absolute target and exact adjacent relative form are accepted.
rm -- "$control_env"
ln -s 'live-runtime-key.env' "$control_env"
run_installer "${args[@]}" >/dev/null || fail 'The exact adjacent relative link was not accepted.'
rm -- "$control_env"
ln -s 'other-runtime.env' "$control_env"
before_link_rejection="$(<"$SYSTEMCTL_LOG")"
set +e
link_output="$(run_installer "${args[@]}" 2>&1)"
link_status=$?
set -e
[[ $link_status -ne 0 && "$link_output" == *'approved same-directory runtime env file'* ]] || fail 'An arbitrary control-plane symlink target was accepted.'
[[ "$(<"$SYSTEMCTL_LOG")" == "$before_link_rejection" ]] || fail 'Systemd was reloaded after a symlink validation failure.'
rm -- "$control_env"
ln -s "$home/.config/nebula/live-runtime-key.env" "$control_env"

# An identical rerun is idempotent; a conflicting unit is preserved and rejected.
run_installer "${args[@]}" >/dev/null || fail 'An identical installed unit was not accepted.'
printf '%s\n' 'unexpected replacement' > "$installed"
set +e
conflict_output="$(run_installer "${args[@]}" 2>&1)"
conflict_status=$?
set -e
[[ $conflict_status -ne 0 && "$conflict_output" == *'differs and was not overwritten'* ]] || fail 'A conflicting installed API unit was accepted.'
[[ "$(<"$installed")" == 'unexpected replacement' ]] || fail 'The conflicting unit was overwritten.'

# Incorrect target paths and weak secret permissions fail before systemd reload.
set +e
path_output="$(HOME="$home" PATH="$temp_root/bin:$PATH" bash "$installer" \
  --confirm-credential-rotation --confirm-private-projection-review "$home/other" "$control_env" "$auth_file" 2>&1)"
path_status=$?
set -e
[[ $path_status -ne 0 && "$path_output" == *'exact projects/nebula-live directory'* ]] || fail 'An unexpected repository path was accepted.'
chmod 644 "$auth_file"
set +e
mode_output="$(HOME="$home" PATH="$temp_root/bin:$PATH" bash "$installer" "${args[@]:0:3}" "$control_env" "$auth_file" 2>&1)"
mode_status=$?
set -e
[[ $mode_status -ne 0 && "$mode_output" == *'current-user-owned mode 0600'* ]] || fail 'A weakly protected auth file was accepted.'

# If systemd definition reload fails after the write, the new unit is removed.
chmod 600 "$auth_file"
rm -f -- "$installed"
cp "$repo/scripts/founder-graph/tests/fixtures/fake-systemctl-fail-reload.sh" "$temp_root/bin/systemctl"
chmod +x "$temp_root/bin/systemctl"
: > "$SYSTEMCTL_LOG"
set +e
reload_output="$(HOME="$home" PATH="$temp_root/bin:$PATH" FAIL_RELOAD=1 run_installer "${args[@]}" 2>&1)"
reload_status=$?
set -e
[[ $reload_status -ne 0 && "$reload_output" == *'could not reload unit definitions'* ]] || fail 'A failed systemd reload was reported as successful.'
[[ ! -e "$installed" ]] || fail 'A unit left by a failed definition reload was not rolled back.'

printf '%s\n' 'PASS: API unit installer requires approvals, validates fixed paths, writes gates=1, and never starts/enables.'
