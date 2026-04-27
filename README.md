# ShiftOps

SaaS для оперативного контроля смен в HoReCa, поставляемый как Telegram Web App.

> Linear для баров — премиальный тёмный UI, защита от подмены фотоотчётов, real-time оповещения, мультиарендность с первого дня.

## Стек (зафиксирован)

- **Фронтенд (TWA):** Next.js 14 App Router, TypeScript, Tailwind, shadcn/ui, Zustand, `next-intl`, `@telegram-apps/sdk-react`, Workbox.
- **Бэкенд:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, aiogram 3.x.
- **Данные:** PostgreSQL 16 (с RLS), Redis 7, TaskIQ.
- **Хранилище (MVP):** Telegram (`file_id` + архивный канал) за абстракцией `StorageProvider`; Cloudflare R2 в V2.
- **DevOps:** Docker Compose, Nginx, Hetzner VPS, GitHub Actions, Sentry.

Полная картина и ADR'ы — в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Быстрый старт

```bash
cp .env.example .env
# отредактируйте .env: TG_BOT_TOKEN и секреты
make dev
```

Поднимает Postgres + Redis + API + Web через Docker Compose. API будет на `http://localhost:8000/docs`, TWA — на `http://localhost:3000`.

```bash
make seed       # демо-организация: 3 пользователя и 2 шаблона
make migrate    # применить последние миграции Alembic
make test       # pytest + vitest
make lint       # ruff + eslint
```

## Структура репозитория

```
apps/
  api/              FastAPI-сервис (domain / application / infra / api)
  web/              Next.js TWA
infra/              Docker Compose, конфиги Nginx
docs/               PRD, архитектура, схема, auth, бот, хранилище, дизайн-система
scripts/            Сидер и эксплуатационные скрипты
.github/workflows/  CI/CD
```

## Карта документации

- [PRD](docs/PRD.md) — что и зачем мы строим.
- [Архитектура](docs/ARCHITECTURE.md) — диаграммы и ADR.
- [Схема БД](docs/DATABASE_SCHEMA.md) — ERD + DDL + политики RLS.
- [Auth flow](docs/AUTH_FLOW.md) — Telegram `initData` → JWT → RLS.
- [Telegram-бот](docs/TELEGRAM_BOT.md) — команды, диплинки, матрица уведомлений.
- [Хранилище](docs/STORAGE.md) — TG-only архитектура и план миграции на R2.
- [Дизайн-система](docs/DESIGN_SYSTEM.md) — токены, компоненты, промпты.
- [UX-флоу](docs/UX_FLOW.md) — конечный автомат и крайние случаи.
- [Формула баллов](docs/SCORE_FORMULA.md) — расчёт оценки смены.
- [Безопасность](docs/SECURITY.md) — валидация initData, RLS, anti-fake, GDPR.
- [Наблюдаемость](docs/OBSERVABILITY.md) — логи, метрики, алерты.
- [Деплой](docs/DEPLOY.md) — настройка Hetzner и пайплайн GitHub Actions.
- [Дорожная карта](docs/ROADMAP.md) — V0 → V3.

## Лицензия

Проприетарная. © ShiftOps.
