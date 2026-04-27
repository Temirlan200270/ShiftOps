#!/bin/sh
# Fly.io / supervisor eventlistener protocol: first line must be READY, then we forward events.
# If a program enters FATAL, terminate PID 1 (supervisord) so the machine is replaced.
# Uses POSIX sh only (python:3.12-slim has no bash by default).
# (No `set -e`: `read` returns non-zero at EOF; we should not exit the listener on that edge case.)
printf 'READY\n'
while IFS= read -r line; do
  printf '%s\n' "$line"
  case "$line" in *PROCESS_STATE_FATAL*) kill -TERM 1 ;; esac
done
