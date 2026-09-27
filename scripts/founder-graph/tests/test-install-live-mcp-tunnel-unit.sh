#!/usr/bin/env bash
set -Eeuo pipefail

readonly repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
readonly installer="$repo/scripts/founder-graph/install-live-mcp-tunnel-unit.sh"
readonly temp_root="$(mktemp -d)"
trap 'rm -rf -- "$temp_root"' EXIT

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
mkdir -p "$temp_root/repo/scripts/founder-graph" "$temp_root/home/.config/dots" "$temp_root/bin"
cp "$repo/scripts/founder-graph/dots-live-mcp-tunnel.service" "$temp_root/repo/scripts/founder-graph/"
printf '%s\n' 'fake config, not a credential' > "$temp_root/control-plane.env"
printf '%s\n' 'fake auth bytes, not a credential' > "$temp_root/home/.config/dots/live-neo4j-auth.secret"
chmod 600 "$temp_root/control-plane.env" "$temp_root/home/.config/dots/live-neo4j-auth.secret"

cp "$repo/scripts/founder-graph/tests/fixtures/fake-systemctl.sh" "$temp_root/bin/systemctl"
chmod +x "$temp_root/bin/systemctl"
export SYSTEMCTL_LOG="$temp_root/systemctl.log"

HOME="$temp_root/home" PATH="$temp_root/bin:$PATH" bash "$installer" \
  "$temp_root/repo" "$temp_root/control-plane.env" "$temp_root/home/.config/dots/live-neo4j-auth.secret" >/dev/null || \
  fail 'Valid protected files did not install the dormant unit.'
[[ "$(readlink "$temp_root/home/.config/dots/live-control-plane.env")" == "$temp_root/control-plane.env" ]] || fail 'The env file link did not match the expected path.'
cmp -s "$temp_root/repo/scripts/founder-graph/dots-live-mcp-tunnel.service" "$temp_root/home/.config/systemd/user/dots-live-mcp-tunnel.service" || \
  fail 'The installed unit differs from the source template.'
[[ "$(<"$SYSTEMCTL_LOG")" == '--user daemon-reload' ]] || fail 'The installer did more than a systemd definition reload.'

# Existing conflicting service definitions are never overwritten.
printf '%s\n' 'unrecognized user service' > "$temp_root/home/.config/systemd/user/dots-live-mcp-tunnel.service"
set +e
conflict_output="$(HOME="$temp_root/home" PATH="$temp_root/bin:$PATH" bash "$installer" \
  "$temp_root/repo" "$temp_root/control-plane.env" "$temp_root/home/.config/dots/live-neo4j-auth.secret" 2>&1)"
conflict_status=$?
set -e
[[ "$conflict_status" -ne 0 && "$conflict_output" == *'differs and was not overwritten'* ]] || fail 'A conflicting service was not rejected.'
[[ "$(<"$SYSTEMCTL_LOG")" == '--user daemon-reload' ]] || fail 'The conflicted unit was reloaded.'

# A group/world-readable auth file is rejected before systemd is touched.
chmod 644 "$temp_root/home/.config/dots/live-neo4j-auth.secret"
set +e
acl_output="$(HOME="$temp_root/home" PATH="$temp_root/bin:$PATH" bash "$installer" \
  "$temp_root/repo" "$temp_root/control-plane.env" "$temp_root/home/.config/dots/live-neo4j-auth.secret" 2>&1)"
acl_status=$?
set -e
[[ "$acl_status" -ne 0 && "$acl_output" == *'owner-only mode 0600'* ]] || fail 'An insufficiently protected auth file was accepted.'
[[ "$(<"$SYSTEMCTL_LOG")" == '--user daemon-reload' ]] || fail 'Systemd was touched after an ACL failure.'

printf '%s\n' 'PASS: live unit installer only installs the dormant unit and enforces protected paths.'
