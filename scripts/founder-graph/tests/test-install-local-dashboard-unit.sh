#!/usr/bin/env bash
set -Eeuo pipefail

readonly repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
readonly installer="$repo/scripts/founder-graph/install-local-dashboard-unit.sh"
readonly temp_root="$(mktemp -d)"
trap 'rm -rf -- "$temp_root"' EXIT

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
home="$temp_root/home"
fake_repo="$home/projects/nebula-live"
control_env="$home/.config/nebula/live-control-plane.env"
control_env_target="$home/.config/nebula/live-runtime-key.env"
auth_file="$home/.config/nebula/live-neo4j-auth.secret"
unit_dir="$home/.config/systemd/user"
installed="$unit_dir/nebula-local-dashboard.service"
mkdir -p "$fake_repo/scripts/founder-graph" "$fake_repo/dist" "$home/.config/nebula" "$temp_root/bin"
cp "$repo/scripts/founder-graph/nebula-local-dashboard.service" "$fake_repo/scripts/founder-graph/"
printf '%s\n' 'fake control settings' > "$control_env_target"
printf '%s\n' 'fake auth bytes' > "$auth_file"
printf '%s\n' '<!doctype html>' > "$fake_repo/dist/index.html"
chmod 600 "$control_env_target" "$auth_file"
ln -s "$control_env_target" "$control_env"
cp "$repo/scripts/founder-graph/tests/fixtures/fake-systemctl.sh" "$temp_root/bin/systemctl"
chmod +x "$temp_root/bin/systemctl"
export SYSTEMCTL_LOG="$temp_root/systemctl.log"

run_installer() {
  HOME="$home" PATH="$temp_root/bin:$PATH" bash "$installer" "$fake_repo" "$control_env" "$auth_file"
}

# Missing prerequisites fail before creating the unit or contacting systemd.
mv "$fake_repo/dist/index.html" "$fake_repo/dist/index.missing"
set +e
missing_output="$(run_installer 2>&1)"
missing_status=$?
set -e
[[ $missing_status -ne 0 && "$missing_output" == *'built dashboard is unavailable'* ]] || fail 'A missing dashboard build was accepted.'
[[ ! -e "$installed" && ! -e "$SYSTEMCTL_LOG" ]] || fail 'The missing-prerequisite path installed a unit or called systemd.'
mv "$fake_repo/dist/index.missing" "$fake_repo/dist/index.html"

mv "$auth_file" "$auth_file.missing"
set +e
missing_auth_output="$(run_installer 2>&1)"
missing_auth_status=$?
set -e
[[ $missing_auth_status -ne 0 && "$missing_auth_output" == *'configuration file is unavailable'* ]] || fail 'A missing Neo4j auth file was accepted.'
[[ ! -e "$installed" && ! -e "$SYSTEMCTL_LOG" ]] || fail 'The missing-auth path installed a unit or called systemd.'
mv "$auth_file.missing" "$auth_file"

mv "$control_env_target" "$control_env_target.missing"
set +e
missing_control_output="$(run_installer 2>&1)"
missing_control_status=$?
set -e
[[ $missing_control_status -ne 0 && "$missing_control_output" == *'configuration file is unavailable'* ]] || fail 'A missing control-plane key file was accepted.'
[[ ! -e "$installed" && ! -e "$SYSTEMCTL_LOG" ]] || fail 'The missing-control path installed a unit or called systemd.'
mv "$control_env_target.missing" "$control_env_target"

# Installing the exact fixed template reloads definitions only.
run_installer >/dev/null || fail 'The valid fixed controller unit did not install.'
[[ -f "$installed" ]] || fail 'The fixed controller unit was not written.'
cmp -s "$fake_repo/scripts/founder-graph/nebula-local-dashboard.service" "$installed" || fail 'The installed definition differs from the approved fixed source.'
[[ "$(<"$SYSTEMCTL_LOG")" == '--user daemon-reload' ]] || fail 'The installer started or enabled a user service.'

# A conflicting existing definition is preserved byte-for-byte.
printf '%s\n' 'existing operator definition' > "$installed"
set +e
conflict_output="$(run_installer 2>&1)"
conflict_status=$?
set -e
[[ $conflict_status -ne 0 && "$conflict_output" == *'differs and was not overwritten'* ]] || fail 'A conflicting existing unit was accepted.'
[[ "$(<"$installed")" == 'existing operator definition' ]] || fail 'The conflicting existing unit was overwritten.'

# Only the exact approved same-directory symlink target is accepted.
rm -f -- "$installed" "$control_env"
ln -s "$auth_file" "$control_env"
: > "$SYSTEMCTL_LOG"
set +e
symlink_output="$(run_installer 2>&1)"
symlink_status=$?
set -e
[[ $symlink_status -ne 0 && "$symlink_output" == *'control-plane link points outside'* ]] || fail 'An unexpected control-plane symlink target was accepted.'
[[ ! -e "$installed" && ! -s "$SYSTEMCTL_LOG" ]] || fail 'An invalid control-plane symlink touched the unit or systemd.'
rm -f -- "$control_env"
ln -s "$control_env_target" "$control_env"

# A definition-reload failure removes only the file created by this run.
cp "$repo/scripts/founder-graph/tests/fixtures/fake-systemctl-fail-reload.sh" "$temp_root/bin/systemctl"
chmod +x "$temp_root/bin/systemctl"
: > "$SYSTEMCTL_LOG"
set +e
reload_output="$(HOME="$home" PATH="$temp_root/bin:$PATH" FAIL_RELOAD=1 run_installer 2>&1)"
reload_status=$?
set -e
[[ $reload_status -ne 0 && "$reload_output" == *'could not reload the definition'* ]] || fail 'A failed definition reload was reported as successful.'
[[ ! -e "$installed" ]] || fail 'A unit created before failed definition reload was not rolled back.'
[[ "$(<"$SYSTEMCTL_LOG")" == $'--user daemon-reload\n--user daemon-reload' ]] || fail 'Rollback performed an unexpected systemd action.'

printf '%s\n' 'PASS: dashboard unit installer validates prerequisites, preserves conflicts, reloads definitions only, and rolls back failed installs.'
