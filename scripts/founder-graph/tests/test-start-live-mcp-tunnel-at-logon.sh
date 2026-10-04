#!/usr/bin/env bash
set -Eeuo pipefail

readonly root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
readonly startup="$root/scripts/founder-graph/start-live-mcp-tunnel-at-logon.sh"
readonly test_root="$(mktemp -d)"
trap 'rm -rf -- "$test_root"' EXIT
mkdir -p "$test_root/bin" "$test_root/home/.local/bin"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
write_executable() { local path="$1"; shift; printf '%s\n' "$@" > "$path"; chmod +x "$path"; }

# Fake command budget wrapper; the production script always supplies a deadline.
write_executable "$test_root/bin/timeout" \
  '#!/usr/bin/env bash' \
  'while [[ "$1" == --* ]]; do shift; done' \
  'duration="$1"; shift' \
  'printf "%s %s\\n" "$duration" "$*" >> "$TIMEOUT_LOG"' \
  'exec /usr/bin/timeout "$duration" "$@"'
export TIMEOUT_LOG="$test_root/timeouts.log"
export COMMAND_LOG="$test_root/commands.log"

write_executable "$test_root/docker" \
  '#!/usr/bin/env bash' \
  'printf "docker %s\\n" "$*" >> "$COMMAND_LOG"' \
  'case "$1 $2" in' \
  '  "info --format") [[ "${DOCKER_INFO_DELAY:-0}" == 0 ]] || sleep "$DOCKER_INFO_DELAY"; [[ "${DOCKER_INFO_FAILURE:-0}" == 0 ]] ;;' \
  '  "inspect --format")' \
  '    attempts=0; [[ ! -f "$HOME/db-inspect-attempts" ]] || attempts="$(<"$HOME/db-inspect-attempts")"; attempts=$((attempts + 1)); printf "%s\\n" "$attempts" > "$HOME/db-inspect-attempts"' \
  '    if [[ "${DB_INSPECT_FAILURES:-0}" -ge "$attempts" ]]; then exit 1; fi' \
  '    case "$3" in' \
  '      "{{.State.Status}}") state_attempts=0; [[ ! -f "$HOME/db-state-attempts" ]] || state_attempts="$(<"$HOME/db-state-attempts")"; state_attempts=$((state_attempts + 1)); printf "%s\\n" "$state_attempts" > "$HOME/db-state-attempts"; if [[ "${DB_STATE_CREATED_ONCE:-0}" == 1 && "$state_attempts" == 1 ]]; then printf "created\\n"; else printf "%s\\n" "${DB_STATE:-running}"; fi ;;' \
  '      "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}") if (( attempts <= ${DB_HEALTH_STARTING_CHECKS:-0} )); then printf "starting\\n"; else printf "%s\\n" "${DB_HEALTH:-healthy}"; fi ;;' \
  '      "{{index .Config.Labels \"com.docker.compose.project\"}}") printf "founder-graph-local\\n" ;;' \
  '      "{{index .Config.Labels \"com.docker.compose.service\"}}") printf "neo4j\\n" ;;' \
  '      "{{range .Mounts}}{{if eq .Destination \"/data\"}}{{.Type}}|{{.Name}}{{end}}{{end}}") printf "volume|founder-graph-local_founder_graph_neo4j_data\\n" ;;' \
  '      "{{json .HostConfig.PortBindings}}") printf "{\\\"7474/tcp\\\":[{\\\"HostIp\\\":\\\"127.0.0.1\\\",\\\"HostPort\\\":\\\"7474\\\"}],\\\"7687/tcp\\\":[{\\\"HostIp\\\":\\\"127.0.0.1\\\",\\\"HostPort\\\":\\\"7687\\\"}]}\\n" ;;' \
  '      *) exit 2 ;;' \
  '    esac ;;' \
  '  "volume inspect")' \
  '    case "$4" in' \
  '      "{{index .Labels \"com.openai.founder_graph.role\"}}") printf "%s\\n" "${VOLUME_ROLE:-live}" ;;' \
  '      "{{index .Labels \"com.openai.founder_graph.database\"}}") printf "%s\\n" "${VOLUME_DATABASE:-neo4j}" ;;' \
  '      *) exit 2 ;;' \
  '    esac ;;' \
  '  *) exit 2 ;;' \
  'esac'

write_executable "$test_root/bin/systemctl" \
  '#!/usr/bin/env bash' \
  'printf "systemctl %s\\n" "$*" >> "$COMMAND_LOG"' \
  'if [[ "$1" == --user && "$2" == start ]]; then [[ "${SYSTEMCTL_START_DELAY:-0}" == 0 ]] || sleep "$SYSTEMCTL_START_DELAY"; [[ "${SYSTEMCTL_START_FAILURE:-0}" == 0 ]]; exit $?; fi' \
  'if [[ "$1" == --user && "$2" == show ]]; then printf "%s\\n" "${SERVICE_ENV:-}"; exit 0; fi' \
  'if [[ "$1" == --user && "$2" == is-active ]]; then printf "active\n"; exit 0; fi' \
  'exit 0'
write_executable "$test_root/home/.local/bin/tunnel-client" \
  '#!/usr/bin/env bash' \
  '[[ "$*" == "health --port 8082 --require-control-plane-poll --json" ]] || exit 2' \
  'printf "tunnel-client health probe\n" >> "$COMMAND_LOG"' \
  'attempts=0; [[ ! -f "$HOME/health-attempts" ]] || attempts="$(<"$HOME/health-attempts")"' \
  'attempts=$((attempts + 1)); printf "%s\n" "$attempts" > "$HOME/health-attempts"' \
  '[[ "${TUNNEL_HEALTH_FAILURE:-0}" == 0 ]] || exit 1' \
  'if [[ "${TUNNEL_HEALTH_TRANSIENT:-0}" == 1 && "$attempts" -gt 1 ]]; then printf "%s\n" "{\"result\":\"failed\",\"healthz\":{\"ok\":false,\"status\":503},\"readyz\":{\"ok\":false,\"status\":503},\"control_plane_poll\":{\"ok\":false,\"value\":0}}"; exit 0; fi' \
  'if [[ "${TUNNEL_POLL_FAILURE:-0}" == 1 ]]; then printf "%s\n" "{\"result\":\"ok\",\"healthz\":{\"ok\":true,\"status\":200},\"readyz\":{\"ok\":true,\"status\":200},\"control_plane_poll\":{\"ok\":false,\"value\":0}}"; else printf "%s\n" "{\"result\":\"ok\",\"healthz\":{\"ok\":true,\"status\":200},\"readyz\":{\"ok\":true,\"status\":200},\"control_plane_poll\":{\"ok\":true,\"value\":1790403000}}"; fi'

# Explicitly stopped DB is not started and never touches systemd.
set +e
stopped_output="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" DB_STATE=exited bash "$startup" 2>&1)"
stopped_status=$?
set -e
[[ "$stopped_status" -eq 0 ]] || fail "Stopped DB should leave tunnel unavailable without error: $stopped_output"
[[ "$stopped_output" == *'database is stopped'* ]] || fail 'Stopped DB result was not observable.'
! grep -q '^systemctl ' "$COMMAND_LOG" || fail 'Systemd was touched while DB was stopped.'
! grep -Eq 'docker (start|run|create|restart|compose up|compose create)' "$COMMAND_LOG" || fail 'A command that can start/recreate the live DB was issued.'

# Live tunnel safety flags are required before systemctl start.
: > "$COMMAND_LOG"
set +e
blocked_output="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=0 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=0' bash "$startup" 2>&1)"
blocked_status=$?
set -e
[[ "$blocked_status" -ne 0 ]] || fail 'Unconfirmed live safety flags were accepted.'
[[ "$blocked_output" == *'safety gates'* ]] || fail 'Safety-gate failure was not observable.'
! grep -q -- '--user start nebula-live-mcp-tunnel.service' "$COMMAND_LOG" || fail 'Tunnel start ran without both safety flags.'

# Only healthy live DB plus both exact approval flags may start the separate live unit.
: > "$COMMAND_LOG"
rm -f "$test_root/home/health-attempts"
ready_output="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' bash "$startup" 2>&1)" || \
  fail "Healthy DB with confirmed safety flags should pass: $ready_output"
[[ "$ready_output" == *'[nebula live tunnel startup] Normal database and live MCP tunnel are ready.'* ]] || fail 'Ready result marker was not observable.'
grep -q -- '--user start nebula-live-mcp-tunnel.service' "$COMMAND_LOG" || fail 'Confirmed safe service was not started.'
! grep -Eq 'docker (start|run|create|restart|compose up|compose create)' "$COMMAND_LOG" || fail 'A live DB mutation was issued.'
[[ "$(<"$test_root/home/health-attempts")" == 3 ]] || fail 'The tunnel was not kept healthy across three probes.'

# A transiently absent/uninspectable or starting database is allowed to become
# ready within the same common deadline. No database-start command is issued.
: > "$COMMAND_LOG"
rm -f "$test_root/home/db-inspect-attempts" "$test_root/home/health-attempts"
delayed_database_output="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' DB_INSPECT_FAILURES=1 DB_HEALTH_STARTING_CHECKS=2 bash "$startup" 2>&1)" || \
  fail "A transiently delayed healthy database did not recover: $delayed_database_output"
[[ "$delayed_database_output" == *'[nebula live tunnel startup] Normal database and live MCP tunnel are ready.'* ]] || fail 'Delayed DB readiness marker was not observable.'
[[ "$(<"$test_root/home/db-inspect-attempts")" -ge 4 ]] || fail 'DB inspection was not retried after the initial unavailable result.'
! grep -Eq 'docker (start|run|create|restart|compose up|compose create)' "$COMMAND_LOG" || fail 'A command that can start/recreate the live DB was issued while waiting.'

: > "$COMMAND_LOG"
rm -f "$test_root/home/db-inspect-attempts" "$test_root/home/db-state-attempts" "$test_root/home/health-attempts"
created_database_output="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' DB_STATE_CREATED_ONCE=1 bash "$startup" 2>&1)" || \
  fail "A database transitioning from created to running did not recover: $created_database_output"
[[ "$created_database_output" == *'[nebula live tunnel startup] Normal database and live MCP tunnel are ready.'* ]] || fail 'Created-state startup was not retried to readiness.'
! grep -Eq 'docker (start|run|create|restart|compose up|compose create)' "$COMMAND_LOG" || fail 'A database creation/start command was issued during readiness waiting.'
# Tunnel start failures and failed health probes never become ready states.
short_startup="$test_root/start-live-short.sh"
sed 's/startup_timeout_seconds="${NEBULA_STARTUP_TIMEOUT_SECONDS:-120}"/startup_timeout_seconds="${NEBULA_STARTUP_TIMEOUT_SECONDS:-3}"/' "$startup" > "$short_startup"
: > "$COMMAND_LOG"
set +e
tunnel_start_failure="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' SYSTEMCTL_START_FAILURE=1 bash "$startup" 2>&1)"
tunnel_start_status=$?
set -e
[[ "$tunnel_start_status" -ne 0 && "$tunnel_start_failure" == *'service failed to start'* ]] || fail 'A failed live service start was reported ready.'

: > "$COMMAND_LOG"
set +e
delayed_tunnel_start="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' SYSTEMCTL_START_DELAY=4 bash "$short_startup" 2>&1)"
delayed_tunnel_status=$?
set -e
[[ "$delayed_tunnel_status" -ne 0 && "$delayed_tunnel_start" == *'startup deadline'* ]] || fail 'A delayed tunnel start exceeded the common deadline without failing closed.'

: > "$COMMAND_LOG"
set +e
tunnel_health_failure="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' TUNNEL_HEALTH_FAILURE=1 bash "$short_startup" 2>&1)"
tunnel_health_status=$?
set -e
[[ "$tunnel_health_status" -ne 0 && "$tunnel_health_failure" == *'did not remain healthy'* ]] || fail 'A failed tunnel health probe was reported ready.'

: > "$COMMAND_LOG"
rm -f "$test_root/home/health-attempts"
set +e
transient_tunnel_health="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' TUNNEL_HEALTH_TRANSIENT=1 bash "$short_startup" 2>&1)"
transient_tunnel_status=$?
set -e
[[ "$transient_tunnel_status" -ne 0 && "$transient_tunnel_health" == *'lost health during its stability check'* ]] || \
  fail 'A one-shot tunnel health response followed by MCP failure was reported ready.'

: > "$COMMAND_LOG"
set +e
missing_poll_output="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' TUNNEL_POLL_FAILURE=1 bash "$short_startup" 2>&1)"
missing_poll_status=$?
set -e
[[ "$missing_poll_status" -ne 0 && "$missing_poll_output" == *'did not remain healthy'* ]] || \
  fail 'A successful health endpoint without a successful control-plane poll was reported ready.'

# Unhealthy database remains fail closed and does not start the tunnel.
: > "$COMMAND_LOG"
set +e
unhealthy_output="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" DB_HEALTH=unhealthy SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' bash "$short_startup" 2>&1)"
unhealthy_status=$?
set -e
[[ "$unhealthy_status" -ne 0 && "$unhealthy_output" == *'did not become ready within 120 seconds'* ]] || fail 'Unhealthy DB was not safely withheld at the startup deadline.'
! grep -q -- '--user start nebula-live-mcp-tunnel.service' "$COMMAND_LOG" || fail 'Tunnel started with unhealthy DB.'

# Use a three-second copy for a real delay/failure case without waiting for the
# production 120-second ceiling. Later commands must receive a reduced budget.
set +e
 : > "$COMMAND_LOG"
 : > "$TIMEOUT_LOG"
delayed_output="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" TIMEOUT_LOG="$TIMEOUT_LOG" SERVICE_ENV='NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1 NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' DOCKER_INFO_DELAY=2.5 bash "$short_startup" 2>&1)"
delayed_status=$?
set -e
[[ "$delayed_status" -ne 0 ]] || fail 'A delayed startup that consumed the remaining deadline was reported as ready.'
! grep -q -- '--user start nebula-live-mcp-tunnel.service' "$COMMAND_LOG" || fail 'A deadline overrun still started the tunnel.'
maximum_timeout="$(awk '{value=$1; sub(/s$/, "", value); value*=1000; if (value > max) max=value} END {print max+0}' "$TIMEOUT_LOG")"
[[ "$maximum_timeout" -le 3000 ]] || fail 'A delayed step received more than the total startup budget.'
[[ "$(wc -l < "$TIMEOUT_LOG")" -le 5 ]] || fail 'Too many checks continued after the delayed step consumed the startup deadline.'
awk '{value=$1; sub(/s$/, "", value); if (NR > 1 && value > previous) exit 1; previous=value} END {if (NR < 1) exit 1}' "$TIMEOUT_LOG" || \
  fail 'The remaining startup budget did not decrease across delayed operations.'
[[ "$(grep -c 'docker inspect' "$COMMAND_LOG" || true)" -le 4 ]] || fail 'Docker inspections continued after the remaining startup budget was exhausted.'

: > "$COMMAND_LOG"
set +e
failed_engine_output="$(PATH="$test_root/bin:$PATH" NEBULA_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" COMMAND_LOG="$COMMAND_LOG" DOCKER_INFO_FAILURE=1 bash "$short_startup" 2>&1)"
failed_engine_status=$?
set -e
[[ "$failed_engine_status" -ne 0 && "$failed_engine_output" == *'Docker Engine did not become ready'* ]] || fail 'Docker Engine failure did not fail closed.'
! grep -q -- '--user start nebula-live-mcp-tunnel.service' "$COMMAND_LOG" || fail 'Tunnel started while Docker Engine was unavailable.'

# The PowerShell task uses wait-only mode after persisting its finite startup
# result. This mode must not run the startup script a second time.
write_executable "$test_root/bin/systemctl-inactive" \
  '#!/usr/bin/env bash' \
  '[[ "$*" == "--user is-active --quiet nebula-live-mcp-tunnel.service" ]] || exit 2' \
  'exit 3'
mkdir -p "$test_root/keepalive-bin"
ln -s "$test_root/bin/systemctl-inactive" "$test_root/keepalive-bin/systemctl"
keepalive_output="$(PATH="$test_root/keepalive-bin:$PATH" bash "$root/scripts/founder-graph/keep-live-mcp-tunnel-alive.sh" --wait-only 2>&1)" || \
  fail "Wait-only keepalive did not exit safely when the tunnel is inactive: $keepalive_output"
[[ "$keepalive_output" == *'Tunnel is inactive'* ]] || fail 'Wait-only mode did not report an inactive tunnel.'

printf '%s\n' 'PASS: live tunnel logon startup remains fail-closed and never starts the database.'
