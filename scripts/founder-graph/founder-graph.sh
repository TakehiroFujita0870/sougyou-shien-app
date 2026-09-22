#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
COMPOSE_FILE="$REPO_ROOT/compose.founder-graph.yml"
IMAGE="neo4j:5.26-community"
LIVE_VOLUME_KEY="founder_graph_neo4j_data"
RESTORE_VOLUME_PREFIX="founder-graph-restore-"
AUTH_SECRET_FILE=""
AUTH_FILE_WAS_SET=""
AUTH_FILE_ORIGINAL=""
RESTART_REQUIRED=0

usage() {
  cat <<'EOF'
Usage:
  founder-graph.sh validate
  founder-graph.sh start
  founder-graph.sh stop
  founder-graph.sh status
  founder-graph.sh backup <output-directory>
  founder-graph.sh restore <backup-directory> <new-restore-volume>
  founder-graph.sh verify-restore <restore-volume> <manifest.json>
  founder-graph.sh capture-manifest <queries.json> <manifest.json>

The restore target must be a new labeled volume. The production data volume is
never a valid restore target. Manifest capture requires exactly three
read-only queries and refuses an existing output file.
EOF
}

fail() {
  printf 'founder-graph: %s\n' "$1" >&2
  exit 1
}

require_docker() {
  command -v docker >/dev/null 2>&1 || fail 'Docker CLI is unavailable; run this helper inside WSL2 with Docker available.'
  docker compose version >/dev/null 2>&1 || fail 'Docker Compose v2 is unavailable.'
}

require_auth() {
  [[ -n "${FOUNDER_GRAPH_NEO4J_AUTH:-}" ]] || fail 'Set FOUNDER_GRAPH_NEO4J_AUTH to neo4j/<local-password> for Docker actions.'
  [[ "$FOUNDER_GRAPH_NEO4J_AUTH" == neo4j/* && "${FOUNDER_GRAPH_NEO4J_AUTH#neo4j/}" != "" ]] || fail 'FOUNDER_GRAPH_NEO4J_AUTH must use the neo4j/<local-password> form.'
}

prepare_auth_secret() {
  local old_umask
  old_umask="$(umask)"
  umask 077
  AUTH_SECRET_FILE="$(mktemp "${TMPDIR:-/tmp}/founder-graph-auth.XXXXXX")" || fail 'could not create a private temporary auth file.'
  umask "$old_umask"
  printf '%s' "$FOUNDER_GRAPH_NEO4J_AUTH" > "$AUTH_SECRET_FILE" || fail 'could not write the private temporary auth file.'
  chmod 600 -- "$AUTH_SECRET_FILE" || fail 'could not protect the temporary auth file.'
  if [[ -v FOUNDER_GRAPH_NEO4J_AUTH_FILE ]]; then
    AUTH_FILE_WAS_SET=1
    AUTH_FILE_ORIGINAL="$FOUNDER_GRAPH_NEO4J_AUTH_FILE"
  else
    AUTH_FILE_WAS_SET=0
  fi
  export FOUNDER_GRAPH_NEO4J_AUTH_FILE="$AUTH_SECRET_FILE"
}

cleanup_auth_secret() {
  if [[ -n "$AUTH_SECRET_FILE" && -f "$AUTH_SECRET_FILE" ]]; then
    rm -f -- "$AUTH_SECRET_FILE"
  fi
  if [[ "$AUTH_FILE_WAS_SET" == 1 ]]; then
    export FOUNDER_GRAPH_NEO4J_AUTH_FILE="$AUTH_FILE_ORIGINAL"
  else
    unset FOUNDER_GRAPH_NEO4J_AUTH_FILE || true
  fi
  AUTH_SECRET_FILE=""
}

on_exit() {
  local status=$?
  # Disable the EXIT trap before recovery so a failed health check cannot
  # recursively re-enter this handler and skip credential cleanup.
  trap - EXIT
  if [[ "$RESTART_REQUIRED" -eq 1 ]]; then
    if compose start neo4j && wait_for_healthy; then
      RESTART_REQUIRED=0
    else
      status=1
    fi
  fi
  cleanup_auth_secret
  exit "$status"
}

require_project_name() {
  local project="${FOUNDER_GRAPH_COMPOSE_PROJECT:-founder-graph-local}"
  [[ "$project" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]] || fail 'FOUNDER_GRAPH_COMPOSE_PROJECT must use lowercase Docker project-name characters.'
  [[ "$project" != *,* ]] || fail 'FOUNDER_GRAPH_COMPOSE_PROJECT must not contain commas.'
}

require_python3() {
  command -v python3 >/dev/null 2>&1 || fail 'python3 is required for Founder Graph operations.'
}

reject_comma() {
  [[ "$1" != *,* ]] || fail 'Docker --mount paths and volume names must not contain commas.'
}

wait_for_healthy() {
  local attempt health
  for ((attempt = 0; attempt < 60; attempt += 1)); do
    health="$(compose ps --format '{{.Health}}' neo4j 2>/dev/null || true)"
    if [[ "$health" == *healthy* ]]; then
      return 0
    fi
    sleep 1
  done
  printf 'founder-graph: Neo4j did not become healthy after restart.\n' >&2
  return 1
}

assert_backup_directory() {
  local requested="$1"
  [[ -n "$requested" ]] || fail 'backup requires an output directory.'
  [[ "$requested" = /* ]] || fail 'backup output must be an absolute path outside the repository.'
  reject_comma "$requested"

  local parent candidate canonical
  if [[ -e "$requested" || -L "$requested" ]]; then
    [[ -d "$requested" ]] || fail 'backup output must be a directory.'
    [[ ! -L "$requested" ]] || fail 'backup output must not be a symlink.'
    canonical="$(cd -- "$requested" && pwd -P)"
  else
    parent="$(dirname -- "$requested")"
    [[ -d "$parent" ]] || fail 'backup output parent must already exist.'
    [[ ! -L "$parent" ]] || fail 'backup output parent must not be a symlink.'
    parent="$(cd -- "$parent" && pwd -P)"
    candidate="$parent/$(basename -- "$requested")"
    case "$candidate" in
      "$REPO_ROOT"|"$REPO_ROOT"/*|/data|/data/*)
        fail 'backup output must not be the repository or a data path.'
        ;;
    esac
    (umask 077 && mkdir -- "$candidate") || fail 'could not create private backup output.'
    canonical="$(cd -- "$candidate" && pwd -P)"
  fi

  case "$canonical" in
    "$REPO_ROOT"|"$REPO_ROOT"/*|/data|/data/*)
      fail 'backup output must not be the repository or a data path.'
      ;;
  esac
  [[ -z "$(find -P "$canonical" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail 'backup output must be empty; existing dumps are never overwritten.'

  local mode world_digit
  mode="$(stat -c '%a' -- "$canonical" 2>/dev/null)" || fail 'could not inspect backup output permissions.'
  world_digit="${mode: -1}"
  [[ "$world_digit" =~ ^[0-3]$ ]] || fail 'backup output must not be world-readable.'
  BACKUP_DIRECTORY="$canonical"
}

assert_restore_source() {
  local requested="$1"
  [[ -n "$requested" ]] || fail 'restore requires a backup directory.'
  [[ "$requested" = /* ]] || fail 'restore source must be an absolute path.'
  reject_comma "$requested"
  [[ -d "$requested" && ! -L "$requested" ]] || fail 'restore source must be a regular non-symlink directory.'
  local canonical
  canonical="$(cd -- "$requested" && pwd -P)"
  case "$canonical" in
    "$REPO_ROOT"|"$REPO_ROOT"/*|/data|/data/*)
      fail 'restore source must not be the repository or a data path.'
      ;;
  esac
  [[ -f "$canonical/neo4j.dump" && ! -L "$canonical/neo4j.dump" ]] || fail 'restore source must contain a regular neo4j.dump.'
  [[ -f "$canonical/system.dump" && ! -L "$canonical/system.dump" ]] || fail 'restore source must contain a regular system.dump.'
  BACKUP_DIRECTORY="$canonical"
}

validate_restore_volume() {
  local volume="$1"
  reject_comma "$volume"
  [[ "$volume" =~ ^founder-graph-restore-[a-z0-9][a-z0-9_.-]{0,180}$ ]] || fail 'restore volume must match founder-graph-restore-<lowercase-suffix>.'
  case "$volume" in
    "$LIVE_VOLUME_KEY"|founder-graph-neo4j-data|founder-graph-restore-live|founder-graph-restore-production)
      fail 'restore volume name aliases the live volume.'
      ;;
  esac
  RESTORE_VOLUME="$volume"
}

compose() {
  docker compose --file "$COMPOSE_FILE" "$@"
}

validate_contract() {
  require_python3
  python3 "$SCRIPT_DIR/validate_local_ops.py" --root "$REPO_ROOT"
}

backup() {
  assert_backup_directory "${1:-}"
  local output_dir="$BACKUP_DIRECTORY"

  compose stop neo4j
  RESTART_REQUIRED=1

  compose run --rm --no-deps \
    --volume "$output_dir:/backups" \
    neo4j neo4j-admin database dump neo4j \
    --to-path=/backups

  compose run --rm --no-deps \
    --volume "$output_dir:/backups" \
    neo4j neo4j-admin database dump system \
    --to-path=/backups

  # The flag is cleared only after both start and health checks succeed. If a
  # dump fails, the EXIT handler still attempts a healthy restart.
  compose start neo4j
  wait_for_healthy
  RESTART_REQUIRED=0
  [[ -s "$output_dir/neo4j.dump" ]] || fail 'Neo4j dump was not created.'
  [[ -s "$output_dir/system.dump" ]] || fail 'system database dump was not created.'
  printf 'Backup written to %s (neo4j.dump, system.dump)\n' "$output_dir"
}

restore() {
  assert_restore_source "${1:-}"
  local backup_dir="$BACKUP_DIRECTORY"
  validate_restore_volume "${2:-}"
  local restore_volume="$RESTORE_VOLUME"
  local project="${FOUNDER_GRAPH_COMPOSE_PROJECT:-founder-graph-local}"
  require_project_name
  if docker volume inspect "$restore_volume" >/dev/null 2>&1; then
    fail "Refusing an existing restore volume: $restore_volume"
  fi

  docker volume create \
    --label com.openai.founder_graph.role=restore \
    --label com.openai.founder_graph.database=neo4j \
    --label "com.openai.founder_graph.project=$project" \
    --label "com.openai.founder_graph.source=$backup_dir" \
    "$restore_volume" >/dev/null
  local role database
  role="$(docker volume inspect --format '{{ index .Labels "com.openai.founder_graph.role" }}' "$restore_volume")"
  database="$(docker volume inspect --format '{{ index .Labels "com.openai.founder_graph.database" }}' "$restore_volume")"
  [[ "$role" == restore && "$database" == neo4j ]] || fail 'new restore volume labels must be role=restore,database=neo4j.'

  # Official Neo4j 5 syntax: database load neo4j and database load system.
  docker run --pull never --rm --network none --user neo4j \
    --mount "type=volume,source=$restore_volume,target=/data" \
    --mount "type=bind,source=$backup_dir,target=/backups,readonly" \
    "$IMAGE" neo4j-admin database load \
    neo4j --from-path=/backups --overwrite-destination=true
  docker run --pull never --rm --network none --user neo4j \
    --mount "type=volume,source=$restore_volume,target=/data" \
    --mount "type=bind,source=$backup_dir,target=/backups,readonly" \
    "$IMAGE" neo4j-admin database load \
    system --from-path=/backups --overwrite-destination=true
  printf 'Restore loaded into isolated volume %s\n' "$restore_volume"
}

verify_restore() {
  require_python3
  validate_restore_volume "${1:-}"
  [[ -n "${2:-}" ]] || fail 'verify-restore requires a manifest JSON path.'
  reject_comma "$2"
  python3 "$SCRIPT_DIR/verify_restore.py" \
    --volume "$RESTORE_VOLUME" \
    --manifest "$2" \
    --secret-file "$AUTH_SECRET_FILE"
}

capture_manifest() {
  require_python3
  [[ -n "${1:-}" && -n "${2:-}" ]] || fail 'capture-manifest requires queries JSON and output manifest paths.'
  reject_comma "$1"
  reject_comma "$2"
  wait_for_healthy
  local container project
  container="$(compose ps -q neo4j)"
  [[ -n "$container" ]] || fail 'could not resolve the healthy Neo4j container.'
  project="${FOUNDER_GRAPH_COMPOSE_PROJECT:-founder-graph-local}"
  python3 "$SCRIPT_DIR/capture_manifest.py" \
    --container "$container" \
    --queries "$1" \
    --output "$2" \
    --secret-container-path /run/secrets/founder_graph_auth \
    --expected-project "$project"
}

main() {
  local action="${1:-}"
  case "$action" in
    validate)
      validate_contract
      ;;
    start|stop|status|backup|verify-restore|capture-manifest)
      require_docker
      require_auth
      require_project_name
      prepare_auth_secret
      trap on_exit EXIT
      case "$action" in
        start)
          compose up --detach
          wait_for_healthy
          ;;
        stop)
          compose stop neo4j
          ;;
        status)
          compose ps
          ;;
        backup)
          backup "${2:-}"
          ;;
        verify-restore)
          verify_restore "${2:-}" "${3:-}"
          ;;
        capture-manifest)
          capture_manifest "${2:-}" "${3:-}"
          ;;
      esac
      ;;
    restore)
      require_docker
      restore "${2:-}" "${3:-}"
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
