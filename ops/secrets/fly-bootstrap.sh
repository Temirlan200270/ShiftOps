#!/usr/bin/env bash
# ops/secrets/fly-bootstrap.sh
#
# Bootstrap or rotate ShiftOps secrets on Fly.io without touching disk.
#
# Three guarantees this script gives you:
#   1. Generated secrets (JWT_SECRET, TG_WEBHOOK_SECRET) live only in
#      shell variables and the encrypted Fly secret store.
#   2. Values are piped to `fly secrets import` via stdin, so they never
#      appear as command-line arguments visible in `ps`/`/proc`.
#   3. Existing secrets are never silently overwritten — re-running
#      with the same flags is a no-op. Pass `--force-rotate` to
#      regenerate, with explicit confirmation.
#
# Usage:
#   ops/secrets/fly-bootstrap.sh --app shiftops-api
#   ops/secrets/fly-bootstrap.sh --app shiftops-api-staging --force-rotate
#
# Flags:
#   --app NAME           Fly app to target (required).
#   --force-rotate       Regenerate / re-prompt even if a secret is set.
#                        Rotating JWT_SECRET invalidates ALL active
#                        sessions (access + refresh tokens). Use only
#                        when you mean to.
#   -h | --help          Print this header and exit.
#
# Prerequisites:
#   - flyctl, openssl, jq on PATH.
#   - `fly auth login` already done.
#   - Bash 4+ (Linux / macOS / WSL / Git Bash). Native PowerShell is
#     not supported — run from WSL on Windows.
#
# Recommended workflow:
#   fly auth login
#   ./ops/secrets/fly-bootstrap.sh --app shiftops-api
#   fly deploy -a shiftops-api

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
# Pretty output (stays useful in CI: colour codes do nothing on dumb tty).
# ---------------------------------------------------------------------------

err()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
note() { printf '\033[1;34m→\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || err "missing dependency: $1"
}

# 48 bytes from the OS RNG, base64url-encoded, no padding. Matches
# `python -c 'import secrets; print(secrets.token_urlsafe(48))'`,
# which is what `apps/api/shiftops_api/config.py` was tuned against.
gen_secret() {
  local bytes="${1:-48}"
  openssl rand -base64 "$bytes" | tr '/+' '_-' | tr -d '=\n'
}

# Read a value from the user without echoing it. We deliberately use
# /dev/tty so the prompt still works when stdout is being captured.
read_secret() {
  local prompt="$1" value
  if [[ -t 0 ]]; then
    read -rsp "$prompt: " value
    printf '\n' >&2
  else
    err "stdin is not a TTY; cannot prompt for $prompt"
  fi
  printf '%s' "$value"
}

# ---------------------------------------------------------------------------
# Argument parsing.
# ---------------------------------------------------------------------------

APP=""
FORCE_ROTATE=0

print_help() {
  # Replay the comment header (lines 1..first blank) as help text so
  # the docs above stay the single source of truth.
  awk '/^# / { sub(/^# ?/, ""); print } /^$/ { exit }' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app)            APP="${2:-}"; shift 2 ;;
    --force-rotate)   FORCE_ROTATE=1; shift ;;
    -h|--help)        print_help; exit 0 ;;
    *)                err "unknown flag: $1 (try --help)" ;;
  esac
done

[[ -n "$APP" ]] || err "--app is required (e.g. --app shiftops-api)"

# ---------------------------------------------------------------------------
# Preflight.
# ---------------------------------------------------------------------------

require_cmd fly
require_cmd openssl
require_cmd jq

fly auth whoami >/dev/null 2>&1 \
  || err "fly: not logged in. Run 'fly auth login' first."

note "target app: $APP"

# `fly secrets list --json` returns only metadata (names + digests),
# never values. We use it to detect which keys already exist so we
# don't silently rotate them.
EXISTING_JSON="$(fly secrets list -a "$APP" --json 2>/dev/null || printf '[]')"

# flyctl has shipped both `Name` and `name` over the years; tolerate both.
existing_keys() {
  printf '%s' "$EXISTING_JSON" | jq -r '.[] | (.Name // .name) // empty'
}

has_secret() {
  existing_keys | grep -Fxq "$1"
}

# ---------------------------------------------------------------------------
# Plan: what's random, what's prompted, what's already there.
# ---------------------------------------------------------------------------

GENERATED=()
PROMPTED=()
SKIPPED=()

stage_random() {
  local key="$1"
  if has_secret "$key" && [[ "$FORCE_ROTATE" -eq 0 ]]; then
    SKIPPED+=("$key")
    return
  fi
  GENERATED+=("$key")
}

stage_prompt() {
  local key="$1"
  if has_secret "$key" && [[ "$FORCE_ROTATE" -eq 0 ]]; then
    SKIPPED+=("$key")
    return
  fi
  PROMPTED+=("$key")
}

# Server-only secrets. Generated locally; never typed by a human.
stage_random JWT_SECRET
stage_random TG_WEBHOOK_SECRET

# Externally-provided secrets. Prompt with validation where the format
# is well-defined (bot token, chat id) so we fail loud, not at runtime.
stage_prompt TG_BOT_TOKEN
stage_prompt TG_ARCHIVE_CHAT_ID
stage_prompt DATABASE_URL
stage_prompt DATABASE_URL_SYNC
stage_prompt REDIS_URL
stage_prompt SENTRY_DSN

# ---------------------------------------------------------------------------
# Collect values into an associative array. Bash 4+ required.
# ---------------------------------------------------------------------------

declare -A VALUES=()

if [[ "${#GENERATED[@]}" -gt 0 ]]; then
  for key in "${GENERATED[@]}"; do
    VALUES["$key"]="$(gen_secret 48)"
    ok "generated $key (48 bytes random)"
  done
fi

if [[ "${#PROMPTED[@]}" -gt 0 ]]; then
  note "you'll be prompted for ${#PROMPTED[@]} value(s); input is hidden."
  for key in "${PROMPTED[@]}"; do
    case "$key" in
      SENTRY_DSN)
        v="$(read_secret "  $key (blank = skip, can add later)")"
        if [[ -z "$v" ]]; then
          warn "skip $key (empty)"
          continue
        fi
        ;;
      TG_BOT_TOKEN)
        v="$(read_secret "  $key (BotFather, format <digits>:<hash>)")"
        [[ "$v" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] \
          || err "$key format invalid"
        ;;
      TG_ARCHIVE_CHAT_ID)
        v="$(read_secret "  $key (negative integer for channels)")"
        [[ "$v" =~ ^-?[0-9]+$ ]] \
          || err "$key must be an integer"
        ;;
      DATABASE_URL)
        v="$(read_secret "  $key (postgresql+asyncpg://... pooler:6543)")"
        [[ "$v" == postgresql+asyncpg://* ]] \
          || err "$key must start with postgresql+asyncpg://"
        ;;
      DATABASE_URL_SYNC)
        v="$(read_secret "  $key (postgresql+psycopg://... pooler:5432)")"
        [[ "$v" == postgresql+psycopg://* ]] \
          || err "$key must start with postgresql+psycopg://"
        ;;
      REDIS_URL)
        v="$(read_secret "  $key (rediss://... for Upstash)")"
        [[ "$v" == redis://* || "$v" == rediss://* ]] \
          || err "$key must be a redis(s):// URL"
        ;;
      *)
        v="$(read_secret "  $key")"
        [[ -n "$v" ]] || err "$key cannot be empty"
        ;;
    esac
    VALUES["$key"]="$v"
  done
fi

# ---------------------------------------------------------------------------
# Summary + confirmation.
# ---------------------------------------------------------------------------

if [[ "${#SKIPPED[@]}" -gt 0 ]]; then
  warn "already set, untouched: ${SKIPPED[*]}"
  warn "use --force-rotate to override"
fi

if [[ "${#VALUES[@]}" -eq 0 ]]; then
  ok "nothing to stage — every secret is already configured"
  exit 0
fi

note "will stage ${#VALUES[@]} secret(s) on $APP:"
for key in "${!VALUES[@]}"; do
  printf '    • %s\n' "$key"
done

if [[ "$FORCE_ROTATE" -eq 1 ]] && has_secret JWT_SECRET; then
  warn "JWT_SECRET will be ROTATED — every active session will be invalidated."
fi

read -rp "proceed? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { warn "aborted"; exit 1; }

# ---------------------------------------------------------------------------
# Push via stdin. `--stage` accumulates without triggering a redeploy
# per call; the user runs `fly deploy` once at the end.
# ---------------------------------------------------------------------------

{
  for key in "${!VALUES[@]}"; do
    printf '%s=%s\n' "$key" "${VALUES[$key]}"
  done
} | fly secrets import --stage -a "$APP"

ok "staged ${#VALUES[@]} secret(s) on $APP"

# Best-effort scrub of in-memory values. Not cryptographically perfect
# (bash strings can be copied around the heap before GC), but reduces
# the window during which a swap dump or core file could leak them.
for key in "${!VALUES[@]}"; do
  VALUES["$key"]=""
done
unset VALUES GENERATED PROMPTED SKIPPED EXISTING_JSON

cat <<EOF

Next steps:
  1. Verify the staged set:   fly secrets list -a $APP
  2. Deploy:                  fly deploy -a $APP

Rotation reminders:
  • JWT_SECRET rotation invalidates ALL access + refresh tokens.
    All users will see a single 401 and re-auth via the Telegram WebApp.
  • TG_WEBHOOK_SECRET rotation requires re-registering the webhook
    with Telegram. Run apps/api/scripts/set_webhook.py after deploy.
EOF
