# Deploy: следующие шаги

> Снапшот состояния на момент паузы.
> После Render-фейла (Stripe отказал по карте) возвращаемся к Fly.io.
>
> **Live URLs:**
> - Frontend (Vercel): https://shiftops-web.vercel.app ✅ работает
> - Backend (Fly): https://shiftops-api.fly.dev ⏳ заблокирован — ждём анлок аккаунта
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

- [ ] **U1** — Пройти верификацию на https://fly.io/high-risk-unlock _(сейчас в работе, блокер)_
- [ ] **U2** — `flyctl auth login` после анлока, проверить `flyctl auth whoami`
- [ ] **U3** — Решить судьбу `render.yaml` (см. ниже про коммит удаления)

### 🤖 Что делает агент (после анлока)

- [ ] **A1** — `fly apps create shiftops-api --org personal`
- [ ] **A2** — `fly secrets import` массово из `apps/api/.env.production`
- [ ] **A3** — `fly deploy --remote-only` + `curl /healthz` зелёный
- [ ] **A4** — `fly ssh console -C "alembic upgrade head"` (схема в Supabase)
- [ ] **A5** — `fly ssh console -C "python -m scripts.seed"` (демо-данные пилота, опционально)
- [ ] **A6** — `fly secrets set API_CORS_ORIGINS=...` под фактический Vercel-URL
- [ ] **A7** — Перешить `NEXT_PUBLIC_API_URL` на Vercel → `https://shiftops-api.fly.dev` + редеплой
- [ ] **A8** — Зарегистрировать Telegram webhook на `https://shiftops-api.fly.dev/api/v1/telegram/webhook`
- [ ] **A9** — Добавить GitHub Actions secrets (`FLY_API_TOKEN`, `VERCEL_*`, `TG_*`)
- [ ] **A10** — Прогнать `scripts/smoke_pilot.py` против живого API

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

### U3. Решить судьбу `render.yaml`

Сейчас файл удалён локально, на `main` ещё лежит — Fly его не читает, вреда нет, но для чистоты можно убрать. Когда скажешь, я закоммичу:

```
chore: remove render.yaml — sticking with Fly.io, Render Stripe rejected our card
```

### Сообщить агенту

Когда `flyctl auth whoami` показывает email → пинг агенту, он подхватит дальше.

---

## Детали по шагам агента (после анлока)

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

`Settings → Secrets and variables → Actions → New repository secret`:

| Secret | Откуда |
|---|---|
| `FLY_API_TOKEN` | `fly tokens create deploy --expiry 8760h --app shiftops-api` |
| `VERCEL_TOKEN` | https://vercel.com/account/tokens |
| `VERCEL_ORG_ID` | `apps/web/.vercel/project.json` → `orgId` |
| `VERCEL_PROJECT_ID` | `apps/web/.vercel/project.json` → `projectId` |
| `TG_BOT_TOKEN` | `apps/api/.env.production` |
| `TG_WEBHOOK_SECRET` | `apps/api/.env.production` |
| `SENTRY_AUTH_TOKEN` | (когда подключим Sentry) |

### A10. Smoke-тест

```powershell
python -m scripts.smoke_pilot --base-url https://shiftops-api.fly.dev
```

Проверит: JWT-логин, создание смены, загрузку фото, телеметрию очередей, `/v1/auth/exchange`, метрики Redis-очередей.

---

## Бюджет времени

- Анлок Fly + `flyctl auth login` (юзер): **15 мин – 2 часа** (зависит от ревью).
- Все 10 шагов агента (A1–A10): **15–25 минут** последовательных команд.

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
| `render.yaml` | Render Blueprint | ❌ удалён локально, на `main` лежит остаток |
| `.github/workflows/deploy.yml` | CI/CD pipeline | ✅ написан, ждёт секретов из A9 |
