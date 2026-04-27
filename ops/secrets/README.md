# Fly.io secret bootstrap

A single script — [`fly-bootstrap.sh`](./fly-bootstrap.sh) — does all
secret setup for the API on Fly.io: generates the random ones,
prompts for the externally-supplied ones, and stages them via
`fly secrets import` without ever writing to disk.

## When to run it

| Situation                                  | Command                                                            |
| ------------------------------------------ | ------------------------------------------------------------------ |
| First deploy, secrets store empty          | `./ops/secrets/fly-bootstrap.sh --app shiftops-api`                |
| New staging app, fresh secrets             | `./ops/secrets/fly-bootstrap.sh --app shiftops-api-staging`        |
| Rotate compromised `JWT_SECRET` only       | `./ops/secrets/fly-bootstrap.sh --app shiftops-api --force-rotate` |
| Re-running after one secret was missed     | Same as the first row — already-set keys are skipped automatically |

The script is idempotent: if a key already exists in the Fly secret
store, it is left alone (and reported as `skipped`) unless you pass
`--force-rotate`.

## What it touches

Generated locally (48 bytes from the OS RNG, base64url):

- `JWT_SECRET`
- `TG_WEBHOOK_SECRET`

Prompted (with format validation where it makes sense):

- `TG_BOT_TOKEN` — must match `<digits>:<hash>` (BotFather format)
- `TG_ARCHIVE_CHAT_ID` — integer (negative for channels)
- `DATABASE_URL` — must begin with `postgresql+asyncpg://`
- `DATABASE_URL_SYNC` — must begin with `postgresql+psycopg://`
- `REDIS_URL` — must begin with `redis://` or `rediss://`
- `SENTRY_DSN` — optional, blank = skip

Non-secret config (`APP_ENV`, `API_PUBLIC_URL`, `API_CORS_ORIGINS`,
`STORAGE_PROVIDER`, feature flags, pool sizes …) belongs in the
`[env]` section of `fly.toml`, not here.

## Why a script instead of a documented `fly secrets set` cheatsheet

Three failure modes the script eliminates that the cheatsheet
approach repeatedly hits in practice:

1. **Secret-in-shell-history.** `fly secrets set JWT_SECRET=...`
   typed at the prompt lands in `~/.bash_history`. The script reads
   from `/dev/tty` with echo disabled and pipes to
   `fly secrets import`, so values never appear on a command line.

2. **Secret-in-process-args.** Even without history, the value sits
   in `/proc/<pid>/cmdline` while flyctl is running, readable by
   anyone on the host. `fly secrets import` reads from stdin only.

3. **Accidental rotation of `JWT_SECRET`.** Re-running setup after
   the bot token is wrong shouldn't quietly mint a new JWT key —
   that would invalidate every active session. The script detects
   existing secrets and refuses to touch them without
   `--force-rotate`.

## Prerequisites

- `flyctl` (`fly auth login` already run)
- `openssl`
- `jq`
- Bash 4+ (Linux / macOS / WSL / Git Bash)

On Windows: run from **WSL** or **Git Bash**, not native PowerShell.
The script uses POSIX features (`/dev/tty`, `read -rsp`,
associative arrays) that Windows-native shells don't provide.

## After it runs

```bash
fly secrets list -a shiftops-api    # verify keys (values are never returned)
fly deploy -a shiftops-api          # one redeploy applies the whole batch
```

Staging order matters: `--stage` was used so the API is restarted
exactly once, not once per secret.
