#!/usr/bin/env bash
set -Eeuo pipefail

readonly tunnel_service='dots-live-mcp-tunnel.service'
if [[ $# -eq 1 && "$1" == '--wait-only' ]]; then
  :
elif [[ $# -eq 1 && -f "$1" ]]; then
  bash "$1"
else
  printf '%s\n' '[dots live tunnel keepalive] Startup script unavailable.' >&2
  exit 1
fi
if ! systemctl --user is-active --quiet "$tunnel_service"; then
  printf '%s\n' '[dots live tunnel keepalive] Tunnel is inactive; WSL can stop.'
  exit 0
fi

printf '%s\n' '[dots live tunnel keepalive] Live tunnel is ready; keeping WSL available until sign-out.'
exec sleep infinity
