#!/usr/bin/env bash
set -Eeuo pipefail

readonly repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
readonly startup_script="$repository_root/scripts/founder-graph/start-synthetic-tunnel-at-logon.sh"
readonly test_root="$(mktemp -d)"
trap 'rm -rf -- "$test_root"' EXIT

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

write_executable() {
  local path="$1"
  shift
  printf '%s\n' "$@" > "$path"
  chmod +x "$path"
}

mkdir -p "$test_root/bin" "$test_root/home/.local/bin"

# Simulate timeout without waiting 120 seconds and record the actual budget passed.
write_executable "$test_root/bin/timeout" \
  '#!/usr/bin/env bash' \
  'printf "%s\\n" "$*" >> "$TIMEOUT_LOG"' \
  'exit 124'
timeout_log="$test_root/timeout.log"
export TIMEOUT_LOG="$timeout_log"
docker_log="$test_root/docker.log"
export DOCKER_LOG="$docker_log"
bolt_attempts="$test_root/bolt-attempts"
export BOLT_ATTEMPTS="$bolt_attempts"
tunnel_health_attempts="$test_root/tunnel-health-attempts"
export TUNNEL_HEALTH_ATTEMPTS="$tunnel_health_attempts"
set +e
deadline_output="$(PATH="$test_root/bin:$PATH" DOTS_DOCKER_CLI=/bin/true bash "$startup_script" 2>&1)"
deadline_status=$?
set -e
[[ "$deadline_status" -ne 0 ]] || fail 'A timed-out Docker start was reported as success.'
[[ "$deadline_output" == *'120-second startup deadline'* ]] || fail 'The failure did not state the two-minute deadline.'
grep -Fq '120s /bin/true desktop start' "$timeout_log" || fail 'Docker Desktop start did not receive the full 120-second budget.'

# Execute commands immediately in the harness. This branch confirms an explicitly
# stopped synthetic database exits successfully without starting the tunnel.
write_executable "$test_root/bin/timeout" \
  '#!/usr/bin/env bash' \
  'while [[ "$1" == --* ]]; do shift; done' \
  'if [[ "$1" == 1 && "$2" == bash ]]; then exit 1; fi' \
  'shift' \
  'exec "$@"'
write_executable "$test_root/docker" \
  '#!/usr/bin/env bash' \
  'printf "%s\\n" "$*" >> "$DOCKER_LOG"' \
  'case "$1 $2" in' \
  '  "desktop start"|"info --format") exit 0 ;;' \
  '  "inspect --format") printf "exited\\n"; exit 0 ;;' \
  '  *) exit 2 ;;' \
  'esac'
systemctl_log="$test_root/systemctl.log"
write_executable "$test_root/bin/systemctl" \
  '#!/usr/bin/env bash' \
  'printf "%s\\n" "$*" >> "$SYSTEMCTL_LOG"' \
  'exit 0'
export SYSTEMCTL_LOG="$systemctl_log"
stopped_output="$(PATH="$test_root/bin:$PATH" DOTS_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" bash "$startup_script" 2>&1)" || \
  fail "An explicitly stopped database should leave the tunnel unavailable: $stopped_output"
[[ "$stopped_output" == *'database is stopped'* ]] || fail 'Stopped database result was not observable.'
[[ ! -e "$systemctl_log" ]] || fail 'Tunnel service was touched while the synthetic database was stopped.'
if grep -Eq '(^| )start dots-chatgpt-synthetic-db($| )' "$docker_log"; then
  fail 'The explicitly stopped synthetic database received a start command.'
fi

# Simulate a ready database, Bolt socket, systemd service, and local health client.
write_executable "$test_root/bin/timeout" \
  '#!/usr/bin/env bash' \
  'while [[ "$1" == --* ]]; do shift; done' \
  'if [[ "$1" == 1 && "$2" == bash ]]; then exit 0; fi' \
  'shift' \
  'exec "$@"'
write_executable "$test_root/docker" \
  '#!/usr/bin/env bash' \
  'printf "%s\\n" "$*" >> "$DOCKER_LOG"' \
  'case "$1 $2" in' \
  '  "desktop start"|"info --format") exit 0 ;;' \
  '  "inspect --format") printf "running\\n"; exit 0 ;;' \
  '  *) exit 2 ;;' \
  'esac'
write_executable "$test_root/bin/systemctl" \
  '#!/usr/bin/env bash' \
  'printf "%s\\n" "$*" >> "$SYSTEMCTL_LOG"' \
  'if [[ "$1" == --user && "$2" == is-active ]]; then printf "active\\n"; fi' \
  'exit 0'
write_executable "$test_root/home/.local/bin/tunnel-client" \
  '#!/usr/bin/env bash' \
  '[[ "$1" == health && "$2" == --port && "$3" == 8081 && "$4" == --json ]]'
ready_output="$(PATH="$test_root/bin:$PATH" DOTS_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" bash "$startup_script" 2>&1)" || \
  fail "Ready synthetic services did not pass the startup gate: $ready_output"
[[ "$ready_output" == *'Synthetic database and MCP tunnel are ready.'* ]] || fail 'Ready result was not observable.'
grep -Fq -- '--user start dots-synthetic-tunnel.service' "$systemctl_log" || fail 'Ready database did not start the synthetic tunnel service.'
grep -Fq -- '--user is-active dots-synthetic-tunnel.service' "$systemctl_log" || fail 'Tunnel active state was not checked.'

# Fault-injection cases run a temporary copy with a five-second budget so they
# exercise the real shared-deadline logic without waiting for the production
# 120-second timeout or touching host services.
short_startup_script="$test_root/startup-short-deadline.sh"
sed 's/readonly startup_timeout_seconds=120/readonly startup_timeout_seconds=5/' "$startup_script" > "$short_startup_script"
chmod +x "$short_startup_script"

write_failure_stubs() {
  local docker_mode="$1"
  local systemctl_mode="$2"
  local tunnel_health_mode="$3"

  write_executable "$test_root/bin/timeout" \
    '#!/usr/bin/env bash' \
    'while [[ "$1" == --* ]]; do shift; done' \
    'duration="$1"; shift' \
    'printf "%s %s\\n" "$duration" "$*" >> "$TIMEOUT_LOG"' \
    'if [[ "${BOLT_MODE:-ready}" == failed && "$duration" == 1 && "$1" == bash ]]; then exit 1; fi' \
    'if [[ "${BOLT_MODE:-ready}" == ready-after-retry && "$duration" == 1 && "$1" == bash ]]; then' \
    '  attempts=0; [[ ! -f "$BOLT_ATTEMPTS" ]] || attempts="$(<"$BOLT_ATTEMPTS")"' \
    '  attempts=$((attempts + 1)); printf "%s\\n" "$attempts" > "$BOLT_ATTEMPTS"' \
    '  (( attempts < 2 )) && exit 1' \
    '  exit 0' \
    'fi' \
    'if [[ "${BOLT_MODE:-ready}" == ready && "$duration" == 1 && "$1" == bash ]]; then exit 0; fi' \
    'exec /usr/bin/timeout "$duration" "$@"'

  write_executable "$test_root/docker" \
    '#!/usr/bin/env bash' \
    'printf "%s\\n" "$*" >> "$DOCKER_LOG"' \
    'case "$1 $2" in' \
    "  \"desktop start\") if [[ '$docker_mode' == failed-desktop ]]; then printf 'stub-internal-error-marker\\n' >&2; exit 9; fi; exit 0 ;;" \
    '  "info --format")' \
    "    if [[ '$docker_mode' == delayed-info ]]; then /usr/bin/sleep 1.2; fi" \
    "    if [[ '$docker_mode' == failed-info ]]; then printf 'stub-internal-error-marker\\n' >&2; exit 9; fi" \
    "    if [[ '$docker_mode' == fail-info-once ]]; then count=\$(grep -c '^info ' \"\$DOCKER_LOG\"); if (( count == 1 )); then exit 9; fi; fi" \
    '    exit 0 ;;' \
    '  "inspect --format") printf "running\\n"; exit 0 ;;' \
    '  *) printf "stub-internal-error-marker\\n" >&2; exit 9 ;;' \
    'esac'

  write_executable "$test_root/bin/systemctl" \
    '#!/usr/bin/env bash' \
    'printf "%s\\n" "$*" >> "$SYSTEMCTL_LOG"' \
    "if [[ '$systemctl_mode' == delayed-start && \"\$2\" == start ]]; then /usr/bin/sleep 10; fi" \
    "if [[ '$systemctl_mode' == failed-start && \"\$2\" == start ]]; then printf 'stub-internal-error-marker\\n' >&2; exit 9; fi" \
    'if [[ "$2" == is-active ]]; then printf "active\\n"; fi' \
    'exit 0'

  write_executable "$test_root/home/.local/bin/tunnel-client" \
    '#!/usr/bin/env bash' \
    "if [[ '$tunnel_health_mode' == failed ]]; then printf 'stub-internal-error-marker\\n' >&2; exit 1; fi" \
    'if [[ "${TUNNEL_HEALTH_MODE:-ready}" == ready-after-retry ]]; then' \
    '  attempts=0; [[ ! -f "$TUNNEL_HEALTH_ATTEMPTS" ]] || attempts="$(<"$TUNNEL_HEALTH_ATTEMPTS")"' \
    '  attempts=$((attempts + 1)); printf "%s\\n" "$attempts" > "$TUNNEL_HEALTH_ATTEMPTS"' \
    '  (( attempts < 2 )) && exit 1' \
    'fi' \
    '[[ "$1" == health && "$2" == --port && "$3" == 8081 && "$4" == --json ]]'
}

run_failure_case() {
  local expected_message="$1"
  shift
  local output status
  set +e
  output="$(env "$@" PATH="$test_root/bin:$PATH" \
    DOTS_DOCKER_CLI="$test_root/docker" HOME="$test_root/home" \
    TIMEOUT_LOG="$timeout_log" SYSTEMCTL_LOG="$systemctl_log" DOCKER_LOG="$docker_log" \
    BOLT_ATTEMPTS="$bolt_attempts" TUNNEL_HEALTH_ATTEMPTS="$tunnel_health_attempts" \
    bash "$short_startup_script" 2>&1)"
  status=$?
  set -e
  [[ "$status" -ne 0 ]] || fail "Startup failure case succeeded unexpectedly: $expected_message (timeout log: $(<"$timeout_log"))"
  [[ "$output" == *"$expected_message"* ]] || fail "Startup failure was not observable: $expected_message ($output)"
  [[ "$output" != *'stub-internal-error-marker'* ]] || fail 'A stub internal diagnostic leaked to startup output.'
}

assert_timeout_budgets_are_bounded() {
  local count=0 line budget
  while IFS= read -r line; do
    budget="${line%% *}"
    budget="${budget%s}"
    [[ "$budget" =~ ^[0-9]+$ ]] || fail "A startup subcommand received an invalid timeout budget: $line"
    if (( budget < 1 || budget > 120 )); then
      fail "A startup subcommand received a timeout outside the 1-120 second range: $line"
    fi
    count=$((count + 1))
  done < "$timeout_log"
  (( count > 0 )) || fail 'No startup subcommand timeout budgets were recorded.'
}

# A delayed Docker readiness check consumes the same deadline as later Bolt
# retries; Bolt never opens, and the tunnel must not be started.
: > "$timeout_log"
: > "$systemctl_log"
write_failure_stubs delayed-info success ready
run_failure_case 'Bolt port did not become ready' BOLT_MODE=failed
grep -Eq '^[345]s .*desktop start$' "$timeout_log" || fail 'The startup sequence did not begin with the configured shared budget.'
grep -Eq '^[1-4]s .*inspect' "$timeout_log" || fail 'Later startup work did not receive the reduced shared deadline.'
[[ ! -s "$systemctl_log" ]] || fail 'Tunnel was touched before Bolt readiness succeeded.'
assert_timeout_budgets_are_bounded

# A new logon attempt starts a fresh deadline and can recover after the
# previous attempt exhausted its budget.
: > "$timeout_log"
: > "$systemctl_log"
: > "$docker_log"
write_failure_stubs immediate success ready
restarted_output="$(env PATH="$test_root/bin:$PATH" DOTS_DOCKER_CLI="$test_root/docker" \
  HOME="$test_root/home" TIMEOUT_LOG="$timeout_log" SYSTEMCTL_LOG="$systemctl_log" \
  DOCKER_LOG="$docker_log" BOLT_ATTEMPTS="$bolt_attempts" \
  TUNNEL_HEALTH_ATTEMPTS="$tunnel_health_attempts" BOLT_MODE=ready \
  bash "$short_startup_script" 2>&1)" || fail "A fresh post-timeout attempt did not recover: $restarted_output"
[[ "$restarted_output" == *'Synthetic database and MCP tunnel are ready.'* ]] || \
  fail 'The fresh post-timeout attempt did not finish ready.'

# A Docker Engine that repeatedly rejects readiness is retried only within the
# common budget. The pause itself must also be bounded by the remaining time.
: > "$timeout_log"
: > "$systemctl_log"
: > "$docker_log"
write_failure_stubs failed-info success ready
run_failure_case 'Docker Engine did not become ready within the 120-second startup deadline.'
grep -Eq '^[1-4]s sleep 2$' "$timeout_log" || fail 'Docker Engine retry sleep was not bounded by the shared deadline.'
assert_timeout_budgets_are_bounded

# Docker Desktop CLI failure is reported without exposing child diagnostics or
# proceeding to Engine inspection/Tunnel startup.
: > "$timeout_log"
: > "$systemctl_log"
: > "$docker_log"
write_failure_stubs failed-desktop success ready
run_failure_case 'Docker Desktop startup failed or exceeded the 120-second startup deadline'
! grep -q '^info ' "$docker_log" || fail 'Docker Engine was inspected after Docker Desktop failed to start.'
[[ ! -s "$systemctl_log" ]] || fail 'Tunnel was touched after Docker Desktop failed to start.'
assert_timeout_budgets_are_bounded

# A transient Engine error can recover on the next poll without resetting the
# shared deadline; a completely timed-out launch can also be retried cleanly.
: > "$timeout_log"
: > "$systemctl_log"
: > "$docker_log"
write_failure_stubs fail-info-once success ready
retry_output="$(env PATH="$test_root/bin:$PATH" DOTS_DOCKER_CLI="$test_root/docker" \
  HOME="$test_root/home" TIMEOUT_LOG="$timeout_log" SYSTEMCTL_LOG="$systemctl_log" \
  DOCKER_LOG="$docker_log" BOLT_ATTEMPTS="$bolt_attempts" \
  TUNNEL_HEALTH_ATTEMPTS="$tunnel_health_attempts" BOLT_MODE=ready \
  bash "$short_startup_script" 2>&1)" || fail "Engine retry did not recover: $retry_output"
[[ "$retry_output" == *'Synthetic database and MCP tunnel are ready.'* ]] || fail 'Engine retry did not finish ready.'
(( $(grep -c '^info ' "$docker_log") >= 2 )) || fail 'The failed Engine readiness check was not retried.'

# Bolt readiness can arrive on a later probe while consuming the same deadline.
: > "$timeout_log"
: > "$systemctl_log"
: > "$docker_log"
rm -f -- "$bolt_attempts"
write_failure_stubs immediate success ready
bolt_retry_output="$(env PATH="$test_root/bin:$PATH" DOTS_DOCKER_CLI="$test_root/docker" \
  HOME="$test_root/home" TIMEOUT_LOG="$timeout_log" SYSTEMCTL_LOG="$systemctl_log" \
  DOCKER_LOG="$docker_log" BOLT_ATTEMPTS="$bolt_attempts" \
  TUNNEL_HEALTH_ATTEMPTS="$tunnel_health_attempts" BOLT_MODE=ready-after-retry \
  bash "$short_startup_script" 2>&1)" || fail "Delayed Bolt readiness did not recover: $bolt_retry_output"
[[ "$(<"$bolt_attempts")" -ge 2 ]] || fail 'Bolt readiness was not retried.'
assert_timeout_budgets_are_bounded

# A Tunnel service start that exceeds its remaining budget exits nonzero with
# the sanitized startup error; its stub diagnostic must not leak.
: > "$timeout_log"
: > "$systemctl_log"
write_failure_stubs immediate delayed-start ready
run_failure_case 'tunnel service failed to start or exceeded the 120-second startup deadline' BOLT_MODE=ready
grep -Fq -- '--user start dots-synthetic-tunnel.service' "$systemctl_log" || fail 'The delayed Tunnel start was not exercised.'
assert_timeout_budgets_are_bounded

# A Tunnel service start that fails immediately reports a sanitized error and
# does not poll health as if startup had succeeded.
: > "$timeout_log"
: > "$systemctl_log"
: > "$docker_log"
write_failure_stubs immediate failed-start ready
run_failure_case 'tunnel service failed to start or exceeded the 120-second startup deadline'
grep -Fq -- '--user start dots-synthetic-tunnel.service' "$systemctl_log" || \
  fail 'The failed Tunnel service start was not exercised.'
! grep -Fq -- '--user is-active dots-synthetic-tunnel.service' "$systemctl_log" || \
  fail 'Tunnel health was polled after the service start failed.'

# A delayed Tunnel health response may succeed on the next probe before the
# shared deadline expires.
: > "$timeout_log"
: > "$systemctl_log"
: > "$docker_log"
rm -f -- "$tunnel_health_attempts"
write_failure_stubs immediate success ready
tunnel_retry_output="$(env PATH="$test_root/bin:$PATH" DOTS_DOCKER_CLI="$test_root/docker" \
  HOME="$test_root/home" TIMEOUT_LOG="$timeout_log" SYSTEMCTL_LOG="$systemctl_log" \
  DOCKER_LOG="$docker_log" BOLT_ATTEMPTS="$bolt_attempts" \
  TUNNEL_HEALTH_ATTEMPTS="$tunnel_health_attempts" TUNNEL_HEALTH_MODE=ready-after-retry \
  BOLT_MODE=ready bash "$short_startup_script" 2>&1)" || \
  fail "Delayed Tunnel health did not recover: $tunnel_retry_output"
[[ "$(<"$tunnel_health_attempts")" -ge 2 ]] || fail 'Tunnel health was not retried.'
assert_timeout_budgets_are_bounded

# An active service whose health endpoint never becomes ready exhausts the
# same deadline and reports failure instead of a successful startup.
: > "$timeout_log"
: > "$systemctl_log"
write_failure_stubs immediate success failed
run_failure_case 'did not become healthy within the 120-second startup deadline' BOLT_MODE=ready
grep -Fq -- '--user is-active dots-synthetic-tunnel.service' "$systemctl_log" || fail 'Tunnel health polling was not exercised.'
assert_timeout_budgets_are_bounded

printf '%s\n' 'PASS: 120-second budget is shared, Bolt/Tunnel failure paths are observable and redacted, stopped DB stays unpublished, and ready synthetic services pass.'
