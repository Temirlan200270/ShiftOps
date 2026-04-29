# ShiftOps

**Оперативный контроль смен в HoReCa** — Telegram Web App (TWA): чек-листы открытия/закрытия, фото-доказательства, anti-fake, балл смены, мультиарендность с RLS с первого дня.

---

## Возможности

| Область | Что есть |
|--------|-----------|
| **Смены** | Шаблоны задач, старт/закрытие, отчёт и формула балла |
| **Команда** | Инвайты по ссылке; смена ролей admin↔operator и деактивация — **только владелец** организации или **платформенный super-admin** (`SUPER_ADMIN_TG_ID`) |
| **Бот** | `/start` с `inv_*`, команды владельца (`/team_list`, `/set_role`, `/remove_member`), super-admin (`/org_*`), профиль бота через `setMyDescription` / `setMyCommands` |
| **TWA** | Single-route Next.js, онбординг при первом запуске, офлайн-очередь (Workbox) |

Подробнее о продукте и границах V0 — в [**PRD**](docs/PRD.md) и [**UX-флоу**](docs/UX_FLOW.md).

---

## Стек

| Слой | Технологии |
|------|------------|
| **Фронт (TWA)** | Next.js 14 (App Router), TypeScript, Tailwind, shadcn/ui, Zustand, `next-intl`, `@telegram-apps/sdk-react`, Workbox, Vitest |
| **API** | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, aiogram 3, TaskIQ |
| **Данные** | PostgreSQL 16 + RLS, Redis 7 |
| **Медиа (MVP)** | `StorageProvider` → Telegram (`file_id` + архивный чат); план R2 — в [**STORAGE**](docs/STORAGE.md) |
| **Наблюдаемость** | structlog, Prometheus (`/metrics`), Sentry |

**Прод (фаза 1):** API на [Fly.io](https://fly.io) (`fra`), фронт на [Vercel](https://vercel.com), Postgres [Supabase](https://supabase.com) (pooler), Redis [Upstash](https://upstash.com). Пошагово — [**DEPLOY**](docs/DEPLOY.md). Фаза 2 (self-hosted) описана там же.

---

## Быстрый старт

```bash
cp .env.example .env
# Заполните TG_BOT_TOKEN, JWT_SECRET и остальное по комментариям в .env.example

make dev
```

Поднимается стек из **Docker Compose** (`infra/docker-compose.yml`): Postgres, Redis, API, worker, web. Логи в терминале.

| URL | Назначение |
|-----|------------|
| http://localhost:8000/docs | OpenAPI (в `production` отключён) |
| http://localhost:3000 | TWA |

### Частые команды

```bash
make migrate   # alembic upgrade head (в контейнере api)
make seed      # демо-организация, пользователи, шаблоны
make test      # pytest + vitest
make lint      # ruff + eslint
make fmt       # ruff format + prettier
```

Без Docker (хост): `make install` — `uv sync` в `apps/api` и `pnpm install` в `apps/web`.

Новая миграция: `make revision m="краткое описание"`.

---

## Структура репозитория

```
apps/
  api/shiftops_api/    # domain · application · infra · api/v1 · config
  api/alembic/         # миграции
  api/scripts/       # seed, smoke_pilot
  web/                 # Next.js TWA (app/, components/, lib/, messages/)
infra/                 # docker-compose.yml, nginx
docs/                  # архитектура, схема БД, auth, бот, деплой, …
scripts/               # вспомогательные скрипты (например deploy)
.github/workflows/    # CI/CD: API, Vercel, cron-warmup
```

Чистая архитектура API и диаграммы — [**ARCHITECTURE**](docs/ARCHITECTURE.md).

---

## Документация

| Документ | Содержание |
|----------|------------|
| [PRD](docs/PRD.md) | Продукт и приоритеты |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Слои, RLS, ADR |
| [DATABASE_SCHEMA](docs/DATABASE_SCHEMA.md) | Таблицы и политики RLS |
| [AUTH_FLOW](docs/AUTH_FLOW.md) | `initData` → JWT → RLS |
| [TELEGRAM_BOT](docs/TELEGRAM_BOT.md) | Команды, диплинки, уведомления, профиль бота |
| [STORAGE](docs/STORAGE.md) | Telegram-хранилище и путь к R2 |
| [DESIGN_SYSTEM](docs/DESIGN_SYSTEM.md) | Токены и UI |
| [UX_FLOW](docs/UX_FLOW.md) | Состояния смены/задач, онбординг, команда |
| [SCORE_FORMULA](docs/SCORE_FORMULA.md) | Балл смены |
| [SECURITY](docs/SECURITY.md) | initData, anti-fake, GDPR |
| [OBSERVABILITY](docs/OBSERVABILITY.md) | Логи и метрики |
| [DEPLOY](docs/DEPLOY.md) | Fly, Vercel, секреты, теги релиза |
| [PILOT_SMOKE](docs/PILOT_SMOKE.md) | Чеклист перед пилотом |
| [ROADMAP](docs/ROADMAP.md) | V0 → V3 |

Контекст для ассистентов в репозитории: [**CLAUDE.md**](CLAUDE.md).

---

## Лицензия

Проприетарная. © ShiftOps.
