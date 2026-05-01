# Безопасность

## Аутентификация

- Telegram `initData` валидируется HMAC-SHA256 c `TG_BOT_TOKEN` (см.
  [AUTH_FLOW.md](AUTH_FLOW.md)).
- Окно `auth_date`: 24 часа. Replay'и за пределами отклоняются.
- JWT HS256, `JWT_SECRET` ≥ 32 байт (контролируется в настройках через
  Pydantic `Field(min_length=32)`).
- Refresh-токен в cookie `httpOnly; SameSite=Strict; Secure`, scope —
  только origin API.

## Авторизация

- На уровне приложения: декоратор `@requires(role, scope)` на каждом
  хендлере.
- На уровне БД: RLS Postgres по GUC `app.org_id` — defence in depth.
- Межарендный integration-тест в CI должен оставаться зелёным, чтобы
  релиз дошёл до прода.

## FORCE RLS и привилегированный доступ

Миграция включает `FORCE ROW LEVEL SECURITY` на бизнес-таблицах: **владелец
таблицы больше не обходит политики**. Обычный HTTP‑запрос после JWT выставляет
`app.org_id` (`set_org_guc`) и работает строго внутри арендатора.

**Выбранная стратегия (вариант A):** кросс‑арендные операции выполняют
`SET LOCAL ROLE shiftops_rls_bypass` (роль с атрибутом `BYPASSRLS`) **только**
через единую точку входа в коде — `enter_privileged_rls_mode()` в
[`apps/api/shiftops_api/infra/db/rls.py`](../apps/api/shiftops_api/infra/db/rls.py).
Там же инкрементируется метрика `shiftops_privileged_rls_bypass_total{reason=...}`
и пишется structlog‑событие `rls.privileged_enter`. Новый bypass в приложении
**не** добавлять сырым SQL.

> Почему не `row_security=off`? Для обычных ролей Postgres трактует
> `row_security=off` как “**падай**, если запрос затронул бы RLS-политику”
> (так делает `pg_dump`). Это **не** отключает политики.

| Режим | Кто | Как |
|--------|-----|-----|
| Tenant (по умолчанию) | FastAPI после `require_user` / refresh | `set_org_guc` |
| Системный (нет org до lookup) | Exchange initData, redeem invite, create org, bot super‑admin | `enter_privileged_rls_mode` с устойчивым `reason` |
| Воркер (sweep по всем org) | `recurring_shifts_tick` и аналоги | `enter_privileged_rls_mode`, короткая транзакция |

**Вариант B (на будущее):** отдельный пользователь БД с атрибутом `BYPASSRLS` и
отдельный `DATABASE_URL` для воркера — если политика безопасности запретит
`SET ROLE` из роли приложения. Сейчас в репозитории один runtime URL
(`Settings.database_url`) для API и TaskIQ; миграции используют
`DATABASE_URL_SYNC` / `ALEMBIC_DATABASE_URL` (см. [`settings.py`](../apps/api/shiftops_api/config/settings.py)).

**Операционный чеклист (discovery):** в Supabase → Project Settings → Database
посмотреть пользователя в URI; на Fly — `fly secrets list -a shiftops-api`:
убедиться, что `DATABASE_URL` осознанно один для API+worker или заведены
раздельные секреты, если перейдёте на вариант B.

## Anti-fake (фото)

- Сервер ставит `captured_at_server = now()`. Часам клиента **никогда**
  не доверяем.
- Perceptual hash: `imagehash.phash` поверх загруженного изображения,
  хранится как 64-битный hex. Сравнивается расстоянием Хэмминга с
  последними `ANTIFAKE_HISTORY_LOOKBACK` вложениями для той же пары
  `(template_task_id, location_id)`. Если
  `distance ≤ ANTIFAKE_PHASH_THRESHOLD` (по умолчанию 5) — `suspicious=true`.
- Дополнительно: средняя яркость grayscale; кадры темнее порога
  `antifake_min_mean_luminance_255` помечаются как подозрительные (закрытая
  камера / чёрный кадр), отдельная метрика и тип нарушения `low_luminance`.
- Опциональное сравнение GEO с `location.geo` (200 м). Не блокирует —
  даёт админскому алерту дополнительный контекст.
- На EXIF мы **не** полагаемся: на Android он тривиально подделывается,
  часть iOS-приложений его срезает.

## Согласованность медиа и транзакции БД

`CompleteTaskUseCase` сначала вызывает `StorageProvider.upload()`, затем
сохраняет `Attachment` и коммитит сессию. Если коммит падает после успешной
загрузки (ошибка БД, RLS, обрыв соединения), во внешнем хранилище может
остаться объект без строки в БД. Для Telegram-архива это обычно приемлемый
риск; для платного объектного хранилища (R2 и т.д.) заложите паттерн outbox,
компенсирующее удаление или порядок «черновик в БД → финализация после
успешной загрузки».

## Безопасность webhook

- Telegram-webhook защищён заголовком
  `X-Telegram-Bot-Api-Secret-Token`, сверяемым с `TG_WEBHOOK_SECRET`.
  В каждом окружении свой 32-символьный случайный токен.

## Rate-limit

- Per-IP: Nginx `limit_req` на `/api/v1/auth/exchange` (10/мин) —
  замедляет брутфорс HMAC.
- Per-user: token bucket TaskIQ `send_telegram_message` на чат
  (1/сек) — защита от случайных spam-петель.

## Работа с секретами

- `JWT_SECRET`, `TG_BOT_TOKEN`, `R2_SECRET_ACCESS_KEY` типизированы
  как `pydantic.SecretStr`. Логгер фильтрует эти классы — утечки
  отображаются как `***`.
- `.env`-файлы никогда не коммитятся. CI использует GitHub Actions secrets.

## Хранение данных и GDPR / 152-ФЗ

- Фото: по умолчанию 90 дней (настраивается на уровне организации).
  По истечении срока lifecycle-правило R2 удаляет объекты; у вложений в
  Telegram обнуляется `tg_file_id` (TG-side delete для архивного канала
  пока не реализован — задел на будущее).
- Право на удаление: отдельный maintenance-эндпоинт выполняет
  `audit_events_tombstone(user_id)` в привилегированной транзакции (см.
  [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)).
- Право доступа: API-эндпоинт, экспортирующий все вложения и события
  аудита пользователя одним JSON + zip с фото.

## Заголовки

- `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`.
- `X-Content-Type-Options: nosniff`.
- `Referrer-Policy: strict-origin-when-cross-origin`.
- TWA нужен CSP `frame-ancestors 'self' https://web.telegram.org https://*.telegram.org`
  — задаётся в `next.config.mjs`.
- `X-Frame-Options: ALLOWALL` на пути `/`, чтобы TWA можно было
  встроить в Telegram. API остаётся `SAMEORIGIN`.

## Аудит зависимостей

- Включён GitHub Dependabot.
- `pip-audit` в CI на каждом PR.
- `pnpm audit --prod` в CI.

## Threat-model (топ-5)

- Оператор присылает вчерашнее фото → митигируется phash + серверный
  таймстемп.
- Оператор запускает TWA на телефоне друга, чтобы имитировать выполнение
  → митигируется привязкой `initData.user.id` + GEO-ассист.
- Украденный access JWT → 15-минутный TTL ограничивает ущерб; refresh
  лежит в httpOnly-куке — XSS его не вытащит.
- Межарендная атака → RLS + integration-тест.
- Утечка токена бота → токены — SecretStr; ротация описана как runbook
  в `DEPLOY.md`.
