# Deploy: следующие шаги

> Снапшот состояния на момент паузы.
> После Render-фейла (Stripe отказал по карте) возвращаемся к Fly.io.
>
> **Live URLs:**
> - Frontend (Vercel): https://shiftops-web.vercel.app ✅ работает
> - Backend (Fly): https://shiftops-api.fly.dev ⏳ после `deploy_fly_production.ps1` и деплоя
> - DB (Supabase pooler): `aws-0-eu-central-1.pooler.supabase.com` ✅ готов
> - Redis (Upstash): `intimate-elephant-72932.upstash.io` ✅ готов

---

## Полный чек-лист (1:1 с todo-листом агента)

### ✅ Сделано

- [x] Supabase project в eu-central-1
- [x] Supabase: пароль БД + pooler-строки (asyncpg на 6543, psycopg на 5432)
- [x] Upstash Redis в eu-central-1, `rediss://` URL получен
- [x] Регистрация на Fly.io + привязка карты
- [x] Установлен `flyctl` на Windows
- [x] Telegram-бот: `TG_BOT_TOKEN`, `TG_BOT_USERNAME=ShiftOpsBot`, архивный канал `-1003982637830`
- [x] Vercel: проект `shiftops-web` слинкован, `NEXT_PUBLIC_*` env заведены
- [x] Vercel deploy в прод — фронт живой на https://shiftops-web.vercel.app
- [x] Все production-фиксы фронта (`force-dynamic`, `useCallback`, `Button warning`, `i18n` types) запушены в `main`

### ⏳ Что делаешь ты (юзер)

- [x] **U1** — Верификация Fly (high-risk unlock) пройдена
- [ ] **U2** — Один раз в этом терминале: `flyctl auth login` → `flyctl auth whoami` (в CI/агенте токена нет — логин только у тебя локально)
- [x] **U3** — `render.yaml` в `main` отсутствует; отдельный коммит не нужен

### 🤖 Автоматизация и ручные хвосты

Скрипт **`scripts/deploy_fly_production.ps1`** (из корня репо, после U2) выполняет **A1–A6, A8, A10** подряд: приложение, секреты, деплой, `/healthz`, Alembic, seed, CORS + редеплой, `setWebhook`, smoke.

- [ ] **A1–A6, A8, A10** — Запуск: `.\scripts\deploy_fly_production.ps1` (опции: `-SkipSeed`, `-SkipSmoke`, `-SkipVercelEnv`)
- [ ] **A7** — Скрипт сам вызывает `vercel env add` + `vercel deploy --prod`, если установлен Vercel CLI и ты залогинен (`vercel whoami`). Иначе задай `NEXT_PUBLIC_API_URL=https://shiftops-api.fly.dev` в Dashboard Vercel и сделай production deploy вручную.
- [ ] **A9** — Только вручную в GitHub: секреты должны **совпадать с именами в** `.github/workflows/deploy.yml` — см. таблицу ниже (не `TG_BOT_TOKEN`, а суффикс `_PROD`).

---

## Детали по шагам юзера

### U1. Разблокировать Fly-аккаунт

Открыть https://fly.io/high-risk-unlock → пройти верификацию.

Обычно просят:
- селфи с паспортом или ID,
- подтвердить телефон/email,
- иногда дополнительно — пробный платёж $1 (возвращается).

Решение бывает мгновенным, бывает 1–2 часа на ручной ревью.

> **План B**, если карта так и не пройдёт: VPS на Aeza/TimeWeb (€4–5/мес, принимают карты Мир, СБП, крипту, DC во Франкфурте). Тогда `fly.toml` остаётся в репе как референс, но фактический деплой пойдёт через `docker-compose` на VPS + Caddy для HTTPS + GitHub Actions через SSH для CI. Агент готов это раскатать за ~30 минут.

### U2. `flyctl auth login`

После анлока:

```powershell
flyctl auth login
```

Откроется браузер, логин через GitHub. Проверка успеха:

```powershell
flyctl auth whoami
```

Должен показать твой email.

### U3. `render.yaml`

В репозитории файла нет; Blueprint Render не используем.

### Запуск деплоя

1. `flyctl auth whoami` показывает email.  
2. В корне: `.\scripts\deploy_fly_production.ps1`  
3. Потом **A9** вручную (GitHub Secrets для тегов `v*`).

---

## Детали по шагам агента (после анлока)

Тот же порядок выполняет **`scripts/deploy_fly_production.ps1`**; блок ниже — для ручного повтора или отладки.

### A1. Создать приложение

```powershell
fly apps create shiftops-api --org personal
```

### A2. Залить секреты массово

```powershell
Get-Content apps/api/.env.production | fly secrets import --app shiftops-api
```

### A3. Первый деплой

```powershell
fly deploy --remote-only --config apps/api/fly.toml --dockerfile apps/api/Dockerfile
```

Билд идёт на builder-машине Fly, не на твоём Windows, поэтому быстро.

Проверка:

```powershell
curl https://shiftops-api.fly.dev/healthz
```

Должен вернуть `{"ok": true}`.

### A4. Накатить миграции на Supabase

```powershell
fly ssh console --app shiftops-api -C "alembic upgrade head"
```

### A5. Засеять справочники (опционально)

```powershell
fly ssh console --app shiftops-api -C "python -m scripts.seed"
```

Создаст демо-организацию, локации, юзеров и шаблоны для пилота.

### A6. Обновить CORS

```powershell
fly secrets set API_CORS_ORIGINS="https://shiftops-web.vercel.app,http://localhost:3000" --app shiftops-api
```

### A7. Перешить `NEXT_PUBLIC_API_URL` на Vercel

```powershell
vercel env rm NEXT_PUBLIC_API_URL production --yes
echo https://shiftops-api.fly.dev | vercel env add NEXT_PUBLIC_API_URL production
vercel deploy --prod
```

### A8. Telegram webhook

```bash
curl -F "url=https://shiftops-api.fly.dev/api/v1/telegram/webhook" \
     -F "secret_token=<TG_WEBHOOK_SECRET>" \
     https://api.telegram.org/bot<TG_BOT_TOKEN>/setWebhook
```

`<TG_WEBHOOK_SECRET>` и `<TG_BOT_TOKEN>` подставлю из `apps/api/.env.production`.

### A9. GitHub Actions secrets

`Settings → Secrets and variables → Actions → New repository secret`. Имена **как в workflow** (`.github/workflows/deploy.yml`):

| Secret | Откуда |
|---|---|
| `FLY_API_TOKEN` | `fly tokens create deploy --expiry 8760h --app shiftops-api` |
| `VERCEL_TOKEN` | https://vercel.com/account/tokens |
| `VERCEL_ORG_ID` | `apps/web/.vercel/project.json` → `orgId` |
| `VERCEL_PROJECT_ID` | `apps/web/.vercel/project.json` → `projectId` |
| `TG_BOT_TOKEN_PROD` | значение `TG_BOT_TOKEN` из `apps/api/.env.production` |
| `TG_WEBHOOK_SECRET_PROD` | значение `TG_WEBHOOK_SECRET` из `apps/api/.env.production` |
| `API_PUBLIC_URL_PROD` | `https://shiftops-api.fly.dev` |
| `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT` | опционально; шаг release в workflow пропускается, если токена нет |

### A10. Smoke-тест

Скрипт деплоя уже прогоняет smoke. Вручную (из `apps/api`, с теми же переменными, что у API, плюс доступ к Supabase):

```powershell
$env:SMOKE_API_URL = "https://shiftops-api.fly.dev"
python -m scripts.smoke_pilot
```

Проверит: exchange initData, смену, фото, закрытие (см. `smoke_pilot.py`).

---

## Бюджет времени

- `flyctl auth login` (если ещё не): **1 мин**.
- Скрипт A1–A8 + A10 + (опц.) A7: **~15–25 мин** после готового `apps/api/.env.production`.
- A9 (GitHub Secrets): **~5 мин** отдельно.

---

## Состояние файлов (для справки)

| Файл | Назначение | Статус |
|---|---|---|
| `apps/api/fly.toml` | Fly app config | ✅ готов |
| `apps/api/Dockerfile` | Multi-stage build, supervisord | ✅ готов |
| `apps/api/deploy/supervisord.conf` | api + taskiq в одном контейнере | ✅ готов |
| `apps/api/.env.production` | Все продакшн-секреты для `fly secrets import` | ✅ готов (gitignored) |
| `.env` | Локальная разработка | ✅ исправлен (Redis локальный, дубль `TG_ARCHIVE_CHAT_ID` убран) |
| `apps/web/vercel.json` | `framework: nextjs` для монорепы | ✅ закоммичен |
| `apps/web/.vercel/project.json` | Линк на Vercel-проект | ✅ создан (gitignored) |
| `render.yaml` | Render Blueprint | не используется (в репо нет) |
| `.github/workflows/deploy.yml` | CI/CD pipeline | ✅ написан, ждёт секретов из A9 |
