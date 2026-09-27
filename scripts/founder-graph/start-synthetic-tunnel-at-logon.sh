#!/usr/bin/env bash
set -Eeuo pipefail

readonly container_name='dots-chatgpt-synthetic-db'
readonly tunnel_service='dots-synthetic-tunnel.service'
readonly health_port='8081'
readonly startup_timeout_seconds=120
deadline=$((SECONDS + startup_timeout_seconds))

log() {
  printf '[dots startup] %s\n' "$1"
}

fail() {
  log "$1"
  exit 1
}

remaining_seconds() {
  local remaining=$((deadline - SECONDS))
  (( remaining > 0 )) || return 1
  printf '%s\n' "$remaining"
}

run_before_deadline() {
  local remaining
  remaining="$(remaining_seconds)" || return 124
  timeout --foreground --kill-after=1s --signal=TERM "${remaining}s" "$@"
}

resolve_docker_cli() {
  if [[ -n "${DOTS_DOCKER_CLI:-}" && -x "$DOTS_DOCKER_CLI" ]]; then
    printf '%s\n' "$DOTS_DOCKER_CLI"
    return 0
  fi

  if command -v docker.exe >/dev/null 2>&1; then
    command -v docker.exe
    return 0
  fi

  if command -v cmd.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
    local local_app_data
    local docker_candidate
    local_app_data="$(run_before_deadline cmd.exe /d /c echo %LOCALAPPDATA% | tr -d '\r')" || return 1
    docker_candidate="$(wslpath -u "$local_app_data")/Programs/DockerDesktop/resources/bin/docker.exe"
    if [[ -x "$docker_candidate" ]]; then
      printf '%s\n' "$docker_candidate"
      return 0
    fi
  fi

  return 1
}

bolt_is_ready() {
  run_before_deadline timeout 1 bash -c 'exec 3<>/dev/tcp/127.0.0.1/7688' >/dev/null 2>&1
}

pause_before_retry() {
  # Keep retry sleeps inside the same end-to-end startup budget.
  run_before_deadline sleep 2
}

docker_cli="$(resolve_docker_cli)" || fail 'Docker Desktop CLI was not found or could not be resolved within the startup deadline; no tunnel was started.'

# The Docker Desktop CLI is idempotent and avoids UI automation.
run_before_deadline "$docker_cli" desktop start >/dev/null 2>&1 || \
  fail 'Docker Desktop startup failed or exceeded the 120-second startup deadline; no tunnel was started.'

until run_before_deadline "$docker_cli" info --format '{{.ServerVersion}}' >/dev/null 2>&1; do
  remaining_seconds >/dev/null || fail 'Docker Engine did not become ready within the 120-second startup deadline.'
  pause_before_retry || true
done

container_state="$(run_before_deadline "$docker_cli" inspect --format '{{.State.Status}}' "$container_name" 2>/dev/null)" || \
  fail 'The synthetic database container was not found or inspection exceeded the 120-second startup deadline; no tunnel was started.'

if [[ "$container_state" != 'running' ]]; then
  log 'The synthetic database is stopped; leaving the tunnel unavailable.'
  exit 0
fi

until bolt_is_ready; do
  remaining_seconds >/dev/null || fail 'The synthetic database Bolt port did not become ready within the 120-second startup deadline.'
  container_state="$(run_before_deadline "$docker_cli" inspect --format '{{.State.Status}}' "$container_name" 2>/dev/null)" || \
    fail 'The synthetic database container became unavailable; no tunnel was started.'
  if [[ "$container_state" != 'running' ]]; then
    log 'The synthetic database stopped during startup; leaving the tunnel unavailable.'
    exit 0
  fi
  pause_before_retry || true
done

run_before_deadline systemctl --user start "$tunnel_service" >/dev/null 2>&1 || \
  fail 'The synthetic MCP tunnel service failed to start or exceeded the 120-second startup deadline.'

until [[ "$(run_before_deadline systemctl --user is-active "$tunnel_service" 2>/dev/null || true)" == 'active' ]] && \
  run_before_deadline "$HOME/.local/bin/tunnel-client" health \
    --port "$health_port" --json >/dev/null 2>&1; do
  remaining_seconds >/dev/null || \
    fail 'The managed synthetic MCP tunnel did not become healthy within the 120-second startup deadline.'
  pause_before_retry || true
done

log 'Synthetic database and MCP tunnel are ready.'
