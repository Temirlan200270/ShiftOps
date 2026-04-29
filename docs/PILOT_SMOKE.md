# Smoke-чеклист пилота — V0

Прогоняем перед каждой установкой пилота (**staging / Fly preview** или
первый платящий клиент), чтобы убедиться: end-to-end-флоу работает в живом
Telegram-клиенте.

Автоматическая половина живёт в [`apps/api/scripts/smoke_pilot.py`](../apps/api/scripts/smoke_pilot.py) —
дёргает API так, будто оно зовётся из TWA. Ручная половина ловит всё,
что API не может доказать (UX TWA, реальная доставка Telegram,
haptics, съёмка фото).

## 0. Pre-flight

- [ ] `docker compose ps` показывает `postgres`, `redis`, `api`,
      `worker`, `web` — все в состоянии healthy.
- [ ] `alembic current` совпадает с последней ревизией.
- [ ] `make seed` (или `docker compose … exec api python -m scripts.seed`) завершился без ошибок.
- [ ] Telegram-webhook зарегистрирован: `getWebhookInfo` возвращает
      URL API и `pending_update_count == 0`.
- [ ] Системный бот добавлен в demo-группу админов с правами **send
      messages** и **edit messages**.

## 1. Автоматический API-smoke (`scripts/smoke_pilot.py`)

```bash
# из корня репозитория, тот же compose, что и у `make dev`:
docker compose -f infra/docker-compose.yml --env-file .env exec api python scripts/smoke_pilot.py
```

Скрипт сделает:

1. POST `/v1/auth/exchange` с синтетическим `initData`, подписанным
   `TG_BOT_TOKEN`, → получить JWT оператора.
2. GET `/v1/shifts/me` → проверить, что засеянная утренняя смена есть.
3. POST `/v1/shifts/{id}/start`.
4. Пройти 5 засеянных задач: фото для 2 critical+photo, без фото для
   остальных.
5. POST `/v1/shifts/{id}/close` → ожидаем `closed_clean`, score ≥ 80.

Критерий прохождения: exit code 0, все переходы залогированы.

## 2. Ручной TWA на реальном устройстве

- iOS (Telegram для iOS, последняя версия из App Store).
- Android (Telegram для Android, последняя из Play Store).

Для каждого:

- [ ] Открыть бота, тапнуть **menu-кнопку** → TWA загружается за <2 с.
- [ ] Splash показывает индикатор загрузки; при первом запуске — короткий онбординг TWA, затем дашборд.
- [ ] Дашборд показывает засеянную «Morning Shift» с `Скоро начало`.
- [ ] Нажать **Начать смену** — хаптика срабатывает, дашборд переходит
      в active.
- [ ] Тапнуть critical+photo задачу — открывается шторка, по «Сделать
      фото» **сразу открывается камера** (без выбора из галереи).
- [ ] Отправка фото показывает loading, шторка закрывается, у строки
      появляется зелёная галочка.
- [ ] Включить airplane mode, выполнить non-critical photo-задачу —
      toast говорит «в очереди». Включить сеть обратно → toast
      исчезает, задача становится зелёной в течение ~5 с без действий
      пользователя.
- [ ] Попробовать закрыть смену с pending critical → кнопка неактивна,
      показывается пояснительная строка.
- [ ] Пропустить `required`-задачу → закрыть смену → подтверждение в
      шторке → закрытие как `closed_with_violations`.

## 3. Уведомления

В группе админов:

- [ ] Сообщение о старте смены пришло за 5 с.
- [ ] Каждый callback решения по waiver обновляет исходное сообщение
      в группе на месте.
- [ ] На закрытии смены приходит альбом со всеми фото (по альбому на
      каждые до 10 фото) в течение 10 с.

В личке собственника:

- [ ] Приходит дубль сообщений о старте и закрытии смены.

## 4. Аудит и RLS

```
psql $DATABASE_URL_SYNC -c "SELECT event_type, occurred_at FROM audit_events ORDER BY occurred_at DESC LIMIT 20;"
```

- [ ] Строки `shift.started`, `task.completed`, `shift.closed` есть
      для smoke-прогона.
- [ ] Попробовать `UPDATE audit_events SET event_type='hacked' …` →
      триггер должен ответить `audit_events is append-only`.
- [ ] Запустить `tests/test_rls_isolation.py` — должен оставаться
      зелёным на пилотной БД (через то же подключение прогоняем
      отдельную орг).

## 5. Sanity-проверка score

- [ ] Score чистого прогона лежит в `[80, 100]`.
- [ ] Принудительно закрыть как `closed_with_violations` → score
      падает примерно на `10–20`.

## Роль гейта на rollback

Если любой пункт выше дважды подряд провалился — пилот ставим на паузу
и заводим issue в Sentry с тегом `pilot-smoke`. Орг не двигаем в
«production trial», пока всё не зелёное.
