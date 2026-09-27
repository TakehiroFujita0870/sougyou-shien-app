#!/usr/bin/env bash
set -Eeuo pipefail

readonly tunnel_service='dots-synthetic-tunnel.service'

log() {
  printf '[dots keepalive] %s\n' "$1"
}

if [[ $# -ne 1 || ! -f "$1" ]]; then
  log 'The synthetic tunnel startup script is unavailable.'
  exit 1
fi

bash "$1"

if ! systemctl --user is-active --quiet "$tunnel_service"; then
  log 'The tunnel is inactive; no WSL keepalive process is needed.'
  exit 0
fi

log 'The synthetic tunnel is ready; keeping this WSL distribution alive until logoff.'
exec sleep infinity
