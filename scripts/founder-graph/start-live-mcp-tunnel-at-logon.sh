#!/usr/bin/env bash
set -Eeuo pipefail

# Separate from the live database preflight: observe only, never start a DB.
readonly container_name='founder-graph-local-neo4j-1'
readonly live_volume_name='founder-graph-local_founder_graph_neo4j_data'
readonly compose_project='founder-graph-local'
readonly tunnel_service='nebula-live-mcp-tunnel.service'
readonly tunnel_health_port='8082'
readonly tunnel_health_stable_checks=3
readonly docker_cli_candidate='/mnt/c/Users/hp/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe'
startup_timeout_seconds="${NEBULA_STARTUP_TIMEOUT_SECONDS:-120}"

log() { printf '[nebula live tunnel startup] %s\n' "$1"; }
fail() { log "$1"; exit 1; }
[[ "$startup_timeout_seconds" =~ ^[0-9]+$ ]] || fail 'The startup timeout was invalid; no tunnel was started.'
startup_timeout_seconds=$((10#$startup_timeout_seconds))
(( startup_timeout_seconds >= 1 && startup_timeout_seconds <= 120 )) || fail 'The startup timeout was invalid; no tunnel was started.'
readonly startup_timeout_seconds
now_milliseconds() {
  local timestamp seconds fraction
  IFS=' ' read -r timestamp _ < /proc/uptime
  seconds="${timestamp%%.*}"
  fraction="${timestamp#*.}00"
  fraction="${fraction:0:3}"
  printf '%s\n' "$((10#$seconds * 1000 + 10#${fraction:0:3}))"
}
deadline_milliseconds=$(( $(now_milliseconds) + startup_timeout_seconds * 1000 ))
remaining_milliseconds() {
  local remaining=$((deadline_milliseconds - $(now_milliseconds)))
  (( remaining > 0 )) || return 1
  printf '%s\n' "$remaining"
}
run_before_deadline() {
  local remaining remaining_seconds
  remaining="$(remaining_milliseconds)" || return 124
  printf -v remaining_seconds '%d.%03d' "$((remaining / 1000))" "$((remaining % 1000))"
  timeout --foreground --kill-after=1s --signal=TERM "${remaining_seconds}s" "$@"
}
pause_before_retry() {
  local requested_milliseconds="${1:-2000}" remaining sleep_duration
  remaining="$(remaining_milliseconds)" || return 124
  (( remaining > requested_milliseconds )) && remaining="$requested_milliseconds"
  printf -v sleep_duration '%d.%03d' "$((remaining / 1000))" "$((remaining % 1000))"
  run_before_deadline sleep "$sleep_duration"
}

check_tunnel_readiness() {
  local health_json
  health_json="$(run_before_deadline "$HOME/.local/bin/tunnel-client" health \
    --port "$tunnel_health_port" --require-control-plane-poll --json 2>/dev/null)" || return 1
  run_before_deadline python3 -c 'import json,sys
try:
    data=json.load(sys.stdin)
except (TypeError, ValueError):
    sys.exit(1)
def ready(name):
    endpoint=data.get(name) if isinstance(data,dict) else None
    return isinstance(endpoint,dict) and endpoint.get("ok") is True and type(endpoint.get("status")) is int and endpoint["status"] == 200
poll=data.get("control_plane_poll") if isinstance(data,dict) else None
ok=(isinstance(data,dict) and data.get("result")=="ok" and ready("healthz") and ready("readyz")
    and isinstance(poll,dict) and poll.get("ok") is True and type(poll.get("value")) is int and poll["value"]>0)
sys.exit(0 if ok else 1)' <<<"$health_json"
}

resolve_docker_cli() {
  if [[ -n "${NEBULA_DOCKER_CLI:-}" && -x "$NEBULA_DOCKER_CLI" ]]; then
    printf '%s\n' "$NEBULA_DOCKER_CLI"
  elif [[ -x "$docker_cli_candidate" ]]; then
    printf '%s\n' "$docker_cli_candidate"
  elif command -v docker.exe >/dev/null 2>&1; then
    command -v docker.exe
  else
    return 1
  fi
}

docker_cli="$(resolve_docker_cli)" || fail 'Docker Desktop CLI was unavailable; no tunnel was started.'
until run_before_deadline "$docker_cli" info --format '{{.ServerVersion}}' >/dev/null 2>&1; do
  remaining_milliseconds >/dev/null || fail 'Docker Engine did not become ready within 120 seconds; no tunnel was started.'
  pause_before_retry || true
done

while :; do
  remaining_milliseconds >/dev/null || fail 'The normal database did not become ready within 120 seconds; no tunnel was started.'
  if container_state="$(run_before_deadline "$docker_cli" inspect --format '{{.State.Status}}' "$container_name" 2>/dev/null)"; then
    if [[ "$container_state" == exited || "$container_state" == dead || "$container_state" == paused ]]; then
      log 'The normal database is stopped; leaving the live tunnel unavailable.'
      exit 0
    fi
    if [[ "$container_state" == running ]] && \
      container_health="$(run_before_deadline "$docker_cli" inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_name" 2>/dev/null)" && [[ "$container_health" == healthy ]]; then
      break
    fi
  fi
  pause_before_retry || true
done

check_live_identity() {
  local format="$1" expected="$2" observed
  observed="$(run_before_deadline "$docker_cli" inspect --format "$format" "$container_name" 2>/dev/null)" || return 1
  [[ "$observed" == "$expected" ]]
}

check_live_identity '{{index .Config.Labels "com.docker.compose.project"}}' "$compose_project" || \
  fail 'The normal database project identity did not match; no tunnel was started.'
check_live_identity '{{index .Config.Labels "com.docker.compose.service"}}' 'neo4j' || \
  fail 'The normal database service identity did not match; no tunnel was started.'
check_live_identity '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Type}}|{{.Name}}{{end}}{{end}}' "volume|$live_volume_name" || \
  fail 'The normal database volume identity did not match; no tunnel was started.'
for label_expectation in 'role|live' 'database|neo4j'; do
  label_name="${label_expectation%%|*}"
  label_value="${label_expectation#*|}"
  observed="$(run_before_deadline "$docker_cli" volume inspect --format "{{index .Labels \"com.openai.founder_graph.$label_name\"}}" "$live_volume_name" 2>/dev/null)" || \
    fail 'The normal database volume labels could not be inspected; no tunnel was started.'
  [[ "$observed" == "$label_value" ]] || fail 'The normal database volume labels did not match; no tunnel was started.'
done
port_bindings="$(run_before_deadline "$docker_cli" inspect --format '{{json .HostConfig.PortBindings}}' "$container_name" 2>/dev/null)" || \
  fail 'The normal database network binding could not be inspected; no tunnel was started.'
remaining_milliseconds >/dev/null || fail 'The 120-second startup deadline was exceeded; no tunnel was started.'
if ! python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); expected={"7474/tcp":[{"HostIp":"127.0.0.1","HostPort":"7474"}],"7687/tcp":[{"HostIp":"127.0.0.1","HostPort":"7687"}]}; sys.exit(0 if d == expected else 1)' <<<"$port_bindings"; then
  fail 'The normal database ports were not bound only to loopback; no tunnel was started.'
fi

service_environment="$(run_before_deadline systemctl --user show "$tunnel_service" --property=Environment --value 2>/dev/null)" || \
  fail 'The live tunnel safety configuration could not be inspected; no tunnel was started.'
credential_gate="$(grep -oE 'NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=[^[:space:]\"]+' <<<"$service_environment" || true)"
egress_gate="$(grep -oE 'NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=[^[:space:]\"]+' <<<"$service_environment" || true)"
if [[ "$credential_gate" != 'NEBULA_LIVE_CREDENTIAL_ROTATION_CONFIRMED=1' || \
      "$egress_gate" != 'NEBULA_LIVE_EGRESS_REVIEW_CONFIRMED=1' ]]; then
  fail 'Live tunnel safety gates are absent or unconfirmed; no tunnel was started.'
fi

run_before_deadline systemctl --user start "$tunnel_service" >/dev/null 2>&1 || \
  fail 'The live MCP tunnel service failed to start or exceeded the 120-second startup deadline.'
stable_health_count=0
while (( stable_health_count < tunnel_health_stable_checks )); do
  service_state="$(run_before_deadline systemctl --user is-active "$tunnel_service" 2>/dev/null || true)"
  if [[ "$service_state" != active ]]; then
    (( stable_health_count == 0 )) || fail 'The live MCP tunnel stopped during its health-stability check.'
  elif check_tunnel_readiness; then
    stable_health_count=$((stable_health_count + 1))
  elif (( stable_health_count > 0 )); then
    fail 'The live MCP tunnel lost health during its stability check.'
  fi

  (( stable_health_count >= tunnel_health_stable_checks )) && break
  remaining_milliseconds >/dev/null || fail 'The live MCP tunnel did not remain healthy within the 120-second startup deadline.'
  pause_before_retry 1000 || true
done

log 'Normal database and live MCP tunnel are ready.'
