#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
[[ "$*" == '--user daemon-reload' && "${FAIL_RELOAD:-0}" != 1 ]]
