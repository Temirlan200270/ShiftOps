# Деплой

Поддерживаются две фазы развёртывания. Фаза 1 — это текущая
прод-цель к запуску пилота; фаза 2 — задокументированный «escape
hatch» на случай, когда трафик / стоимость / уровень контроля
перерастают managed-PaaS-стек.

| Фаза | Бэкенд            | Фронтенд          | Postgres | Redis   | Хранилище | Примерная стоимость |
|------|-------------------|-------------------|----------|---------|-----------|---------------------|
| 1    | Fly.io (1 машина) | Vercel            | Supabase | Upstash | Telegram  | ~$2/мес*            |
| 2    | Hetzner CX22      | Vercel / CF Pages | self-hosted PG | self-hosted Redis | Telegram → R2 | ~€5/мес |

\* В пределах $5 бесплатного кредита Fly. Free-tier Supabase (500 МБ),
free-tier Upstash (10к команд/день), Vercel hobby — всё $0. Платим
только за машину Fly.

---

## Фаза 1 — Fly.io + Vercel + Supabase + Upstash

### 1. Разовый provisioning

#### 1.1 Supabase (Postgres)

1. Создать проект в `eu-central-1` (Франкфурт), чтобы совпадал с
   регионом Fly `fra`.
2. Project Settings → Database → **Connection pooling** → скопировать:
   - URI **Transaction pooler** → как `DATABASE_URL` (async runtime).
   - URI **Session pooler** → как `DATABASE_URL_SYNC` (Alembic / DDL).
3. Заменить префиксы схемы:
   - `postgres://` → `postgresql+asyncpg://` для `DATABASE_URL`.
   - `postgres://` → `postgresql+psycopg://` для `DATABASE_URL_SYNC`.
4. Если `alembic upgrade` падает с `FATAL: Tenant or user not found`, сначала **сбросить пароль БД** в Supabase и **заново
   скопировать** URI *Session* и *Transaction* pooler из дашборда (без ручной сборки логина).
5. Включить обязательное RLS на каждой таблице
   (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY`). Миграции из репозитория
   делают это автоматически; проверь в Supabase Studio после первой
   миграции.

> Почему пулер, а не прямой `db.<ref>.supabase.co:5432`?
> На бесплатном проекте Supabase **прямой** хост часто доступен **только по IPv6**. Машины Fly
> на shared-cpu **без IPv6-egress** до такого хоста не достучатся (пока не купить **IPv4 add-on** у
> Supabase). **Pooler** (`*.pooler.supabase.com`) двухстековый с IPv4 — поэтому и `DATABASE_URL`, и
> `fly ssh … alembic` должны использовать **только pooler**, не Direct.
>
> Миграции **с ноутбука** с **рабочим IPv6** (или GitHub Actions) иногда делают с **Direct** URI; на Windows
> без IPv6 к `db.<ref>.supabase.co` бывает `getaddrinfo failed` — тогда **тот же session pooler** (host
> `*.pooler.supabase.com`, порт 5432), что и для Fly.

#### 1.2 Upstash (Redis)

1. Создать БД в `eu-central-1`.
2. Скопировать **TLS**-строку подключения (`rediss://...`).
3. Поставить как `REDIS_URL` в Fly.

> Потолок free tier — 10к команд/день. TaskIQ + rate-limit-трафик на
> один бар укладывается в ~2к команд/день. Когда упрёмся в потолок,
> либо (а) переносим Redis в саму машину Fly (без доплаты), либо (б)
> апгрейдим Upstash ($0.20 за 100к команд).

#### 1.3 Fly.io

```bash
brew install flyctl   # или: curl -L https://fly.io/install.sh | sh
fly auth login
cd apps/api
fly launch --no-deploy --copy-config --name shiftops-api --region fra
```

`fly.toml` уже в репозитории — `--copy-config` сохраняет его, а
`--no-deploy` даёт выставить секреты до первого старта.

Выставить секреты (один раз):

```bash
fly secrets set --app shiftops-api \
  APP_ENV=production \
  API_PUBLIC_URL=https://shiftops-api.fly.dev \
  API_CORS_ORIGINS=https://shiftops.vercel.app,https://shiftops.example.com \
  DATABASE_URL='postgresql+asyncpg://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres' \
  DATABASE_URL_SYNC='postgresql+psycopg://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres' \
  REDIS_URL='rediss://default:<password>@<endpoint>.upstash.io:6379' \
  JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  TG_BOT_TOKEN='<from @BotFather>' \
  TG_BOT_USERNAME='ShiftOpsBot' \
  TG_WEBHOOK_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  TG_ARCHIVE_CHAT_ID='-100xxxxxxxxxx' \
  STORAGE_PROVIDER=telegram \
  SENTRY_DSN='<from sentry.io>'
```

Всё, что содержит URL-спецсимволы, оборачиваем в одинарные кавычки;
двойные позволят шеллу разверстать `$` и тихо сломают секреты.

**Скрипт `scripts/deploy_fly_production.ps1`:** перед `fly secrets import` он **объединяет** `API_CORS_ORIGINS` из `apps/api/.env.production` с `$VercelFrontendUrl`, `http://localhost:3000` и `http://127.0.0.1:3000`. Так мы не затираем кастомные домены (старый вариант перезаписывал секрет только двумя URL и ломал CORS).

#### 1.3a Ошибка деплоя: `Tenant or user not found` (Supabase pooler)

Если `release_command` / `alembic upgrade head` падает с этим текстом на `*.pooler.supabase.com`, на Fly **протухли или неверны** `DATABASE_URL` / `DATABASE_URL_SYNC`.

1. Supabase → **Project Settings** → **Database** → при необходимости **Reset database password**.
2. Скопировать из раздела **Connection pooling** заново:
   - **Transaction pooler** → `DATABASE_URL` с заменой префикса на `postgresql+asyncpg://` и портом **6543**;
   - **Session pooler** → `DATABASE_URL_SYNC` с префиксом `postgresql+psycopg://` и портом **5432**.
3. Выставить секреты и задеплоить:

```bash
cd apps/api
fly secrets set \
  DATABASE_URL='postgresql+asyncpg://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres' \
  DATABASE_URL_SYNC='postgresql+psycopg://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres' \
  --app shiftops-api

fly deploy --remote-only
```

Имя пользователя в URI должно совпадать с тем, что показывает Supabase (часто `postgres.<project-ref>`), без ручной «сборки» строки.

#### 1.4 Vercel (фронтенд)

1. Импортировать `apps/web` как отдельный Vercel-проект (Root Directory
   = `apps/web`, Framework = Next.js). **GitHub Actions** вызывают `vercel` из
   **корня репозитория** (не `cd apps/web`): иначе путь сдваивается
   (`…/apps/web/apps/web`) и деплой падает.
2. Поставить переменные окружения (Production):
   - `NEXT_PUBLIC_API_URL=https://shiftops-api.fly.dev`
   - `NEXT_PUBLIC_TG_BOT_USERNAME=ShiftOpsBot`
3. **По умолчанию** CI подставляет `https://shiftops-api.fly.dev` и `ShiftOpsBot` (см. `.github/workflows/vercel-web.yml`). Чтобы сменить API или бота без правки репо, задай `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_TG_BOT_USERNAME` в **Actions → Variables** или **Secrets** (и то же в Vercel, чтобы везде совпадало).
4. В `API_CORS_ORIGINS` на Fly — прод и свои домены; превью `*.vercel.app` и хосты `*.telegram.org` кроме того **разрешаются в коде** (`allow_origin_regex` в `main.py`), иначе часть клиентов Telegram дала бы `OPTIONS … 400` (CORS).
5. Сохранить `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` как
   GitHub Actions secrets (используются `.github/workflows/deploy.yml`).

> ToS Hobby-tier'а Vercel запрещает «коммерческое» использование. Пока
> ShiftOps в пилоте (бесплатный/внутренний) — всё нормально. В день,
> когда начнём принимать деньги, переключаемся на Vercel Pro
> ($20/мес) или мигрируем на Cloudflare Pages — артефакт сборки
> идентичен, меняется только хост.

### 2. Первый деплой

```bash
cd apps/api
fly deploy --remote-only
```

Смотри логи в другом терминале:

```bash
fly logs --app shiftops-api
```

Ожидаемая последовательность:
1. `supervisord` стартует.
2. `[program:api]` репортит `Application startup complete`.
3. `[program:worker]` репортит `taskiq Worker started`.
4. Health-check Fly на `/healthz` становится зелёным за ~30 с.

### 3. Миграции и сидер

**Миграции:** при каждом `fly deploy` Fly выполняет `[deploy] release_command` из
`apps/api/fly.toml` (`alembic upgrade head` в `/app`) **до** переключения трафика на новый
образ. Если команда падает, деплой не считается успешным. Ручной запуск нужен только
при отладке или если release завис:

```bash
fly ssh console --app shiftops-api --command "alembic upgrade head"
```

**Сидер** (демо-данные, по желанию):

```bash
fly ssh console --app shiftops-api --command "python -m scripts.seed"
```

### 4. Зарегистрировать Telegram-webhook

```bash
TG_BOT_TOKEN='<token>'
TG_WEBHOOK_SECRET='<secret>'
API_URL='https://shiftops-api.fly.dev'

curl -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/setWebhook" \
  -d "url=${API_URL}/api/v1/telegram/webhook" \
  -d "secret_token=${TG_WEBHOOK_SECRET}" \
  -d "allowed_updates=[\"message\",\"callback_query\",\"my_chat_member\"]"

curl "https://api.telegram.org/bot${TG_BOT_TOKEN}/getWebhookInfo"
```

`pending_update_count` должен быть 0, а `last_error_date` — пустым.

### 5. Кастомный домен (опционально)

```bash
fly certs add api.shiftops.app --app shiftops-api
# добавь CNAME из вывода в DNS, затем:
fly certs show api.shiftops.app --app shiftops-api
```

Для Vercel — добавить apex / `app.`-поддомен в настройках проекта и
указать соответствующие DNS-записи.

### 6. Эксплуатация (Day-2 ops)

| Действие              | Команда                                                                                 |
|-----------------------|-----------------------------------------------------------------------------------------|
| Логи в реальном времени | `fly logs --app shiftops-api`                                                          |
| Открыть shell         | `fly ssh console --app shiftops-api`                                                    |
| Перезапустить машину  | `fly machine restart <id> --app shiftops-api`                                           |
| Миграция вручную      | Обычно не нужна (см. `release_command` в `fly.toml`); при сбое: `fly ssh console --command "alembic upgrade head"` |
| Откатить релиз        | `fly releases --app shiftops-api` затем `fly deploy --image registry.fly.io/...:<old-tag>` |
| Поднять RAM           | `fly scale memory 1024 --app shiftops-api`                                              |
| Разделить процессы    | Отредактировать `[processes]` в `fly.toml`, разделить `api`/`worker`, затем `fly deploy` |

### 7. CI/CD пайплайн

`.github/workflows/deploy.yml` стартует по тегам `v*` или вручную:

1. **backend** — `flyctl deploy --remote-only` (миграции в `release_command`), затем
   переустановка Telegram-webhook'а.
2. **frontend** — стартует после успеха backend'а, вызывает
   `vercel deploy --prebuilt --prod`.
3. **release-notes** — тегает релиз в Sentry.

Требуемые GitHub Actions secrets:

| Секрет                  | Назначение                                                |
|-------------------------|-----------------------------------------------------------|
| `FLY_API_TOKEN`         | `fly auth token` — full org token, в env `production`     |
| `VERCEL_TOKEN`          | Vercel personal token                                     |
| `VERCEL_ORG_ID`         | из `.vercel/project.json` после `vercel link`             |
| `VERCEL_PROJECT_ID`     | то же                                                      |
| `TG_BOT_TOKEN_PROD`     | прод-токен бота (нужен для переустановки webhook'а)        |
| `TG_WEBHOOK_SECRET_PROD`| прод-секрет webhook'а                                     |
| `API_PUBLIC_URL_PROD`   | например `https://shiftops-api.fly.dev`                   |
| `SENTRY_AUTH_TOKEN`     | опционально, тихо пропускается при отсутствии             |
| `SENTRY_ORG`            | опционально                                               |
| `SENTRY_PROJECT`        | опционально                                               |

Выпустить релиз:

```bash
git tag -a v0.1.0 -m "MVP pilot"
git push origin v0.1.0
```

### 8. Контроль расходов

- Поставить billing-алерт на `$5/мес` в дашборде Fly.
- Смотреть usage Upstash в начале 2-й недели — если идём за 5к
  команд/день, на курсе ткнуться в потолок, нужен план.
- Supabase ставит проект на паузу после 7 дней неактивности на free
  tier'е; ночной cron в CI (см. `.github/workflows/cron-warmup.yml`)
  держит его тёплым.

---

## Фаза 2 — Hetzner CX22 (когда переросли фазу 1)

Переезжаем, когда **любое** из этого становится правдой:
- Машина Fly стабильно ловит OOM, даже после апгрейда до 1 ГБ.
- Регулярно превышаем daily-cmd ceiling Upstash.
- Нужен >1 регион и multi-region на Fly выходит дороже фикс-платы
  Hetzner'а.
- Нужен прямой доступ к БД / сети для аналитических нагрузок.

Железо: Hetzner CX22 (€4.51/мес, 2 vCPU, 4 ГБ RAM, 40 ГБ SSD,
Ubuntu 24.04). Снапшоты ежедневно + off-site `pg_dump` в Backblaze B2
еженедельно.

### Bootstrap сервера

```bash
ssh root@<host>
adduser shiftops && usermod -aG sudo,docker shiftops
ssh-copy-id shiftops@<host>

sed -i 's/^#PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload sshd

ufw default deny incoming && ufw default allow outgoing
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw enable

curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
```

### Bootstrap приложения

```bash
git clone https://github.com/<org>/shiftops.git ~/shiftops
cd ~/shiftops && cp .env.example .env
# заполнить прод-секреты (DATABASE_URL — на локальный сервис Postgres,
# REDIS_URL — на локальный сервис Redis)
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
```

### TLS

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo cp infra/nginx/shiftops.conf /etc/nginx/sites-available/shiftops
sudo ln -s /etc/nginx/sites-available/shiftops /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d shiftops.example.com
```

### Перенаправить Telegram-webhook

Тот же вызов `setWebhook`, что и в фазе 1, только меняем `url=` на
новый домен.

### План миграции фаза 1 → фаза 2

1. Снять `pg_dump` с Supabase, импортировать в локальный Postgres на
   Hetzner.
2. Поднять стек Hetzner с `APP_ENV=staging` и отдельным ботом.
3. Прогнать smoke-пилот (`scripts/smoke_pilot.py`) против staging-URL.
4. В момент свитчовера: остановить машину Fly (`fly scale count 0`),
   указать DNS на Hetzner, перерегистрировать прод-webhook. Суммарный
   downtime ≤ 5 мин.
5. Держать машину Fly 7 дней как мгновенный rollback
   (`fly scale count 1`).

Workflow деплоя для фазы 2 будет жить в
`.github/workflows/deploy-hetzner.yml` (зеркалит предыдущий
SSH-based-флоу); этот файл намеренно ещё не создан, чтобы не было двух
конкурирующих пайплайнов.

---

## Ротации (для обеих фаз)

- `JWT_SECRET`: ротация раз в квартал. Деплоить с обоими — старым и
  новым — принимаемыми 24 часа, затем дропнуть старый.
- `TG_BOT_TOKEN`: требует revoke + reset через `@BotFather`. **Это
  инвалидирует все `file_id` в Telegram-хранилище** — планируйте на
  off-hours, готовьтесь к re-resolve через `forward_message` из
  архивного канала.
- `TG_WEBHOOK_SECRET`: ротация в любое время — просто вызвать
  `setWebhook` с новым значением (CI и так делает это на каждом
  релизе).
- `FLY_API_TOKEN`: ротация после каждого изменения в команде.

## Disaster recovery

- **Фаза 1:** Supabase даёт PITR на платных планах; на free tier
  полагаемся на ежедневный логический dump-cron
  (`.github/workflows/nightly-pgdump.yml` — `pg_dump` против
  session-pooler URL с заливкой артефакта).
- **Фаза 2:** `pg_dump` ежедневно в Backblaze B2 прямо с Hetzner-а.
- Цель RPO: 24 ч. Цель RTO: 1 ч.
