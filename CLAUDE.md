# ShiftOps — краткий контекст (CLAUDE.md)

ShiftOps — Telegram Web App для контроля смен в HoReCa: чек‑листы, фото‑доказательства, anti‑fake, score, мультиарендность через Postgres RLS.

## TL;DR где что
- `apps/api`: FastAPI + бот (aiogram) + воркер (TaskIQ).
- `apps/web`: Next.js 14 TWA (single-route), TypeScript.
- `infra/docker-compose.yml`: локальный стек.

## Быстрый старт
```bash
cp .env.example .env
make dev
```
URL: API `http://localhost:8000/docs`, TWA `http://localhost:3000`.

## Архитектурные инварианты (не ломать)
- **RLS‑изоляция**: tenant‑контекст ставится через `set_config('app.org_id', ..., true)` в `require_user` (см. `apps/api/shiftops_api/application/auth/deps.py`).
- **Привилегированный доступ**: только через `enter_privileged_rls_mode(...)` (см. `apps/api/shiftops_api/infra/db/rls.py`) с понятным `reason`.
- **Слои API**: domain (без IO) → application (use cases) → infra (реализации) → api (тонкие роуты). Канон: `docs/ARCHITECTURE.md`.

## Команды (Docker Compose)
```bash
make up && make logs
make migrate
make seed
make test
make lint
make fmt
```

## Web: заметка про Windows build
`apps/web/next.config.mjs`: `output: 'standalone'` выключен на Windows по умолчанию (EPERM на symlink). Для форса: `NEXT_FORCE_STANDALONE=1`.

## Каноничные доки (без дублей здесь)
- Product/UX: `README.md`, `docs/PRD.md`, `docs/UX_FLOW.md`, `docs/ROADMAP.md`
- Security/RLS/Auth: `docs/SECURITY.md`, `docs/AUTH_FLOW.md`, `docs/DATABASE_SCHEMA.md`
- Deploy/ops: `docs/DEPLOY.md`, `docs/OBSERVABILITY.md`
- Repo map: `docs/CODEMAP.md`
- Временное (спринт): `docs/sprint/README.md`
