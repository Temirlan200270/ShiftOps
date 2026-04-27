# Deploy: следующие шаги

> Снапшот состояния на момент паузы.
> После Render-фейла (Stripe отказал по карте) возвращаемся к Fly.io.

---

## Что уже готово

- [x] `apps/api/fly.toml` — конфиг приложения, регион Frankfurt, single machine, supervisord
- [x] `apps/api/Dockerfile` — мультистейдж, supervisord (api + taskiq в одном контейнере)
- [x] `apps/api/deploy/supervisord.conf` — два процесса, fail-fast eventlistener
- [x] `apps/api/.env.production` — все секреты в одном файле, готов для `fly secrets import` (gitignored)
- [x] `flyctl` поставлен на Windows
- [x] Supabase project + пароль БД + pooler-строки (asyncpg на 6543, psycopg на 5432)
- [x] Upstash Redis в eu-central-1, `rediss://` URL получен
- [x] Telegram-бот: токен, username `ShiftOpsBot`, архивный канал `-1003982637830`
- [x] Vercel — фронт задеплоен, проект слинкован, `NEXT_PUBLIC_*` env заведены
- [x] Все production-фиксы фронта (`force-dynamic`, `useCallback`, `Button warning`, `i18n` types и др.) запушены в `main`

---

## Осталось — мои шаги (юзера)

### 1. Разблокировать Fly-аккаунт

Открыть https://fly.io/high-risk-unlock → пройти верификацию.

Обычно просят:
- селфи с паспортом или ID,
- подтвердить телефон/email,
- иногда дополнительно — пробный платёж $1 (возвращается).

Решение бывает мгновенным, бывает 1–2 часа на ручной ревью.

> Если карта так и не пройдёт — план B: VPS на Aeza/TimeWeb (€4–5/мес, принимают карты Мир, СБП, крипту, DC во Франкфурте). Тогда `fly.toml` остаётся в репе, но фактический деплой пойдёт через `docker-compose` на VPS.

### 2. `flyctl auth login`

После анлока:

```powershell
flyctl auth login
```

Откроется браузер, логин через GitHub. Проверка успеха:

```powershell
flyctl auth whoami
```

Должен показать email.

### 3. Решить судьбу `render.yaml`

Решение по коммиту:
```
chore: remove render.yaml — sticking with Fly.io, Render Stripe rejected our card
```
(сейчас файл удалён локально, на `main` ещё лежит — Fly его не читает, вреда нет, но для чистоты можно убрать)

### 4. Сообщить агенту

Когда `fly auth whoami` показывает email → пинг агенту, он подхватит дальше.

---

## Осталось — шаги агента (после анлока)

1. **Создать приложение**
   ```powershell
   fly apps create shiftops-api --org personal
   ```

2. **Залить секреты массово** из `.env.production`
   ```powershell
   Get-Content apps/api/.env.production | fly secrets import --app shiftops-api
   ```

3. **Первый деплой** (билд на Fly builder, не на Windows)
   ```powershell
   fly deploy --remote-only --config apps/api/fly.toml --dockerfile apps/api/Dockerfile
   ```

4. **Накатить миграции** на Supabase
   ```powershell
   fly ssh console --app shiftops-api -C "alembic upgrade head"
   ```

5. **Засеять справочники** (опционально для пилота)
   ```powershell
   fly ssh console --app shiftops-api -C "python -m scripts.seed"
   ```

6. **Health-check**
   ```powershell
   curl https://shiftops-api.fly.dev/healthz
   ```
   Должен вернуть `{"ok": true}`.

7. **Обновить CORS** под фактический Vercel-URL
   ```powershell
   fly secrets set API_CORS_ORIGINS="https://<vercel-domain>.vercel.app,http://localhost:3000" --app shiftops-api
   ```

8. **Перешить `NEXT_PUBLIC_API_URL`** на Vercel
   ```powershell
   vercel env rm NEXT_PUBLIC_API_URL production --yes
   echo https://shiftops-api.fly.dev | vercel env add NEXT_PUBLIC_API_URL production
   vercel deploy --prod
   ```

9. **Зарегистрировать Telegram webhook**
   ```bash
   curl -F "url=https://shiftops-api.fly.dev/api/v1/telegram/webhook" \
        -F "secret_token=<TG_WEBHOOK_SECRET>" \
        https://api.telegram.org/bot<TG_BOT_TOKEN>/setWebhook
   ```

10. **GitHub Actions secrets** для CI/CD (`Settings → Secrets → Actions`):
    - `FLY_API_TOKEN` — получить через `fly tokens create deploy --expiry 8760h --app shiftops-api`
    - `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
    - `TG_BOT_TOKEN`, `TG_WEBHOOK_SECRET`
    - `SENTRY_AUTH_TOKEN` (когда подключим Sentry)

11. **Smoke-тест** против живого API
    ```powershell
    python -m scripts.smoke_pilot --base-url https://shiftops-api.fly.dev
    ```
    Проверит: JWT-логин, создание смены, загрузку фото, телеметрию очередей.

---

## Бюджет времени

- Анлок Fly + `flyctl auth login` (юзер): **15 мин – 2 часа** (зависит от ревью).
- Все 11 шагов агента: **15–25 минут** последовательных команд.

---

## Если Fly опять заблокирует

План B уже сформулирован выше: **VPS на Aeza или TimeWeb** + наш существующий `docker-compose.yml` + Caddy для HTTPS + GitHub Actions через SSH для CI. Агент готов это раскатать за ~30 минут.
