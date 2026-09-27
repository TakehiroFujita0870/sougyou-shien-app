#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  printf '%s\n' 'Usage: install-synthetic-tunnel-unit.sh <WSL repository> <WSL environment file>' >&2
  exit 2
fi

repo="$1"
env_file="$2"
unit_source="$repo/scripts/founder-graph/dots-synthetic-tunnel.service"
env_link="$HOME/.config/dots/control-plane.env"
unit_directory="$HOME/.config/systemd/user"

if [[ ! -f "$env_file" || -L "$env_file" ]]; then
  printf '%s\n' 'Control-plane environment file must be a regular file.' >&2
  exit 1
fi
if [[ ! -f "$unit_source" || -L "$unit_source" ]]; then
  printf '%s\n' 'Tunnel unit source must be a regular file.' >&2
  exit 1
fi

mkdir -p "$HOME/.config/dots" "$unit_directory"
if [[ -L "$env_link" ]]; then
  [[ "$(readlink -- "$env_link")" == "$env_file" ]] || {
    printf '%s\n' 'Existing control-plane environment link points elsewhere.' >&2
    exit 1
  }
elif [[ -e "$env_link" ]]; then
  printf '%s\n' 'Control-plane environment path already exists and is not a matching link.' >&2
  exit 1
else
  ln -s -- "$env_file" "$env_link"
fi

install -D -m 0644 "$unit_source" "$unit_directory/dots-synthetic-tunnel.service"
systemctl --user daemon-reload
