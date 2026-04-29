# ShiftOps — CLAUDE.md

SaaS для оперативного контроля смен в HoReCa, поставляемый как Telegram Web App (TWA).

## Стек

### Бэкенд (`apps/api`)
- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x async, Alembic
- aiogram 3.x (Telegram-бот, webhook), TaskIQ + Redis (очереди)
- PostgreSQL 16 с RLS, Redis 7
- Pillow + imagehash (anti-fake pHash)
- Sentry, structlog, Prometheus

### Фронтенд (`apps/web`)
- Next.js 14 App Router, TypeScript, Tailwind CSS, shadcn/ui
- Zustand (стейт), next-intl (i18n), @telegram-apps/sdk-react
- Workbox (Service Worker, offline-очередь best-effort)
- pnpm 9, Vitest

### Инфра (прод)
- API: Fly.io (`fra`), фронтенд: Vercel, БД: Supabase, Redis: Upstash
- Docker Compose для локальной разработки (`infra/docker-compose.yml`)

## Структура репозитория

```
apps/
  api/
    shiftops_api/
      domain/       # чистые датаклассы — сущности, enums, Result, score; без IO
      application/  # use case'ы (оркестрируют репозитории + хранилище)
      infra/        # SQLAlchemy-репозитории, TelegramStorage, aiogram-бот, очередь
      api/v1/       # FastAPI-роутеры: auth, shifts, templates, locations, team,
                    # schedule, media, realtime, invites, analytics, telegram
      config/       # pydantic-settings
    alembic/        # миграции
  web/
    app/            # Next.js App Router, single-route (page.tsx → DashboardScreen)
    components/     # UI-компоненты и экраны
    lib/            # auth/handshake, stores (Zustand), утилиты
    messages/       # i18n-файлы (ru, kk, ...)
infra/              # Docker Compose, Nginx-конфиги
docs/               # PRD, архитектура, схема БД, auth, бот, хранилище, UX, безопасность
scripts/            # seed, smoke-тесты
.github/workflows/  # CI/CD (deploy.yml, vercel-web.yml, cron-warmup.yml)
```

## Команды разработчика

```bash
# Локально через Docker Compose
make dev        # поднять стек + tail логов
make up         # только поднять (фон)
make down       # остановить
make migrate    # alembic upgrade head
make seed       # демо-организация (3 пользователя, 2 шаблона)
make test       # pytest + vitest
make lint       # ruff + eslint
make fmt        # ruff format + prettier
make revision m="add foo"  # сгенерировать Alembic-миграцию

# Без Docker (хост-машина)
make install    # uv sync + pnpm install
```

API доступен на `http://localhost:8000/docs`, TWA — на `http://localhost:3000`.

## Архитектура бэкенда

Прагматичная Clean Architecture с жёсткими границами слоёв:

- **Domain** — никогда не импортирует из `application` или `infra`. Возвращает `Result[T, Failure]` вместо исключений на бизнес-сбоях.
- **Application** — use case'ы оркестрируют протоколы репозиториев и хранилища; возвращают `Result`.
- **Infra** — реализует `Protocol`'ы из `application` (репозитории, `StorageProvider`, уведомления).
- **API** — тонкая HTTP-обёртка: Pydantic in → use case → HTTP out.

### Мультиарендность (RLS)
Каждая бизнес-таблица имеет `organization_id`. FastAPI-зависимость `with_tenant_session` ставит `SET LOCAL app.org_id = '<из JWT>'` перед каждым запросом. Привилегированные use case'ы используют `set_role('app_admin')`.

### Auth flow
1. TWA → `Telegram.WebApp.initData` → POST `/api/v1/auth/exchange` с телом `{ "init_data": "..." }`
2. Бэкенд HMAC-валидирует initData с `TG_BOT_TOKEN`, ищет/создаёт пользователя
3. Выпускает JWT (access 15 мин, refresh 7 дней в `httpOnly` cookie)

### Хранилище медиа
`StorageProvider` Protocol с двумя реализациями:
- `TelegramStorage` (MVP) — хранит `(tg_file_id, archive_chat_id, archive_message_id)`; forward_message как fallback
- `R2Storage` (V2, Cloudflare R2) — presigned PUT/GET

Выбор провайдера: `STORAGE_PROVIDER` env-переменная. Фронтенд всегда ходит на `GET /api/v1/media/{uuid}` (302 redirect).

### Фоновые задачи (TaskIQ + Redis)
- `send_telegram_message` — token bucket (1 сообщение/сек на чат)
- `send_telegram_media_group` — пакет до 10 вложений при закрытии смены
- `shift_reminders_tick` — каждую минуту, напоминания T-30/T+15/T-60
- `daily_digest_tick` — 09:00 по timezone каждой локации
- `recurring_shifts_tick` — каждую минуту, материализует смены из
  `templates.default_schedule` (см. `infra/scheduling/tasks.py` и
  `application/templates/recurring_shifts_tick.py`)

### Anti-fake
Серверный timestamp (клиентские часы игнорируются) + pHash (16×16 DCT) каждого вложения. Сравнение по Хэммингу с историей `(template_task_id, location_id)`. Порог и глубина истории — `ANTIFAKE_PHASH_THRESHOLD` / `ANTIFAKE_HISTORY_LOOKBACK`.

## Навигация фронтенда

TWA намеренно **single-route** (`app/page.tsx`): URL не меняется, экраны переключаются локальным React-стейтом (иначе кнопка «назад» Telegram ломает UX). Точка входа: `page.tsx` → `DashboardScreen`.

## Деплой (фаза 1 — текущий прод)

| Сервис    | Платформа                  |
|-----------|----------------------------|
| API       | Fly.io (`shiftops-api`, `fra`) |
| Фронтенд  | Vercel                     |
| Postgres  | Supabase (connection pooler, не прямой хост) |
| Redis     | Upstash TLS                |

Релиз по git-тегу `v*`:
```bash
git tag -a v0.1.0 -m "MVP pilot"
git push origin v0.1.0
```

Это запускает `.github/workflows/deploy.yml`: fly deploy → переустановка webhook → vercel deploy --prod.

Миграции выполняются автоматически через `release_command` в `fly.toml` до переключения трафика.

### Ключевые env-переменные API (Fly secrets)
`APP_ENV`, `API_PUBLIC_URL`, `API_CORS_ORIGINS`, `DATABASE_URL` (asyncpg, pooler), `DATABASE_URL_SYNC` (psycopg, pooler), `REDIS_URL`, `JWT_SECRET`, `TG_BOT_TOKEN`, `TG_BOT_USERNAME`, `TG_WEBHOOK_SECRET`, `TG_ARCHIVE_CHAT_ID`, `SUPER_ADMIN_TG_ID` (опц., платформенный super-admin), `STORAGE_PROVIDER`, `SENTRY_DSN`, `DB_DISABLE_ASYNCPG_STATEMENT_CACHE` (опц., при DuplicatePreparedStatement на pooler)

### Ключевые env-переменные фронтенда (Vercel)
`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_TG_BOT_USERNAME`

### CORS
Превью-URL `*.vercel.app` разрешаются через `allow_origin_regex` в `main.py`. Прод-домены — в `API_CORS_ORIGINS`.

## Документация

| Файл | Содержание |
|------|-----------|
| `docs/PRD.md` | Продуктовые требования |
| `docs/ARCHITECTURE.md` | Диаграммы, слои, ADR |
| `docs/DATABASE_SCHEMA.md` | ERD, DDL, RLS-политики |
| `docs/AUTH_FLOW.md` | initData → JWT → RLS |
| `docs/TELEGRAM_BOT.md` | Команды, диплинки, матрица уведомлений |
| `docs/STORAGE.md` | TG-хранилище и план миграции на R2 |
| `docs/SECURITY.md` | Anti-fake, RLS, GDPR |
| `docs/DESIGN_SYSTEM.md` | Токены, компоненты |
| `docs/UX_FLOW.md` | Конечный автомат и edge cases |
| `docs/SCORE_FORMULA.md` | Расчёт оценки смены |
| `docs/OBSERVABILITY.md` | Логи, метрики, алерты |
| `docs/DEPLOY.md` | Fly.io + Vercel setup, Day-2 ops, disaster recovery |
| `docs/ROADMAP.md` | V0 → V3 |
