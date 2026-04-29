# Дорожная карта

## V0 — MVP (недели 1–5)

Цель: 1 пилотная организация, 1 локация, 3 оператора, 7 дней в проде.

- Аутентификация через Telegram `initData`, JWT, мультиарендность на
  Postgres RLS.
- 2 хардкоженных шаблона (Morning / Evening shift) — без UI-редактора.
- Конечный автомат смены: start, complete task (с фото / без), флоу
  waiver, закрытие (hard / soft block).
- Telegram-уведомления: напоминания операторам, алерты в группу
  админов, зеркало собственнику.
- Хранилище = Telegram (с fallback'ом на `forward_message`) за
  абстракцией `StorageProvider`.
- Anti-fake: серверный таймстемп + perceptual hash + GEO-ассист.
- Аудит-лог (append-only).
- i18n RU / EN, учёт часовых поясов.
- Sentry, healthchecks.
- TWA-экраны S0–S5 (splash, dashboard, task list, task detail, waiver,
  summary).
- Оффлайн-очередь Service Worker для аплоадов фото.

## V1 — Закаливание основания (недели 6–10)

- ~~Live-монитор админа (S8) на WebSocket.~~ ✅ Готово: WS-эндпоинт
  `/v1/realtime/ws` с JWT-аутентификацией, шиной Redis Pub/Sub
  (`infra/realtime/event_bus.py`), HTTP-снимок активных смен
  (`/v1/realtime/active-shifts`), фронт-экран с переподключением и
  лентой событий.
- ~~Аналитический дашборд собственника (S9): распределение score, топ-3
  нарушителя, heatmap.~~ ✅ Готово: `/v1/analytics/overview` с KPI,
  тепловой картой (DOW × hour в локальной TZ локации), топом
  нарушителей и разбивкой по локациям; экран `analytics-screen.tsx`.

  V1.x (расширенная owner-аналитика): произвольный период `from`/`to`,
  тумблер сравнения с предыдущим окном (`compare`), drill-down по
  нарушителю (`OperatorProfileSheet` → `HistoryScreen` с фильтрами
  `user_id`/`location_id`/`from`/`to`), новые карточки разрезов:
  по шаблонам, критичности задач, anti-fake (% подозрительных вложений),
  SLA «опоздание старта» (порог `analytics_sla_late_start_min`,
  default 15 мин) и сравнение оператор vs бармен. На каждый блок
  бэкенд возвращает density-флаг `ok|low|empty`, чтобы экран показывал
  подсказку «мало данных» там, где выводы статистически нестабильны.
- ~~Импорт расписания из CSV.~~ ✅ Готово: `/v1/schedule/import`
  с dry-run, построчной валидацией, резолвом локации/шаблона/оператора
  батчами и проверкой дублей; экран `csv-import-screen.tsx`.
- ~~Эндпоинт метрик Prometheus + борды Grafana.~~ ✅ Готово: `/metrics`
  поверх `prometheus-client` + собственный ASGI-middleware
  (`api/middleware/prometheus.py`), бизнес-счётчики в дispatcher'е
  (shifts/tasks/waivers/attachments), HTTP-гистограмма по route-template,
  два дашборда `ops/grafana/shiftops-{operations,business}.json` —
  портируемые в Grafana Cloud (free tier).
- ~~Заменить ↑/↓-реордер в S7 на честный drag-and-drop.~~ ✅ Готово:
  `@dnd-kit/sortable` + `KeyboardSensor` (touch + клавиатура +
  скрин-ридер). Кнопки ↑/↓ оставлены как fallback-аффорданс на случай,
  если чанк dnd-kit не загрузится.

> Сделано в V0 раньше графика (не перепланировать):
> - Waiver Approve / Reject через инлайн-кнопки в TG (callback-хендлер
>   aiogram в `infra/telegram/bot.py`). Web-only-флоу унесён в чат
>   TG в том же релизе.
> - Формула score формализована (`shiftops_api.domain.score`) и
>   показывается покомпонентно в summary-экране и истории оператора.
> - Экран истории оператора (S6) со sparkline и пагинированным
>   эндпоинтом.
> - UI-редактор шаблонов (S7) — список + редактор с флагами
>   criticality / photo / comment, drag-and-drop через
>   `@dnd-kit/sortable` и кнопочный fallback ↑/↓.

## V0.5 — Чек-листы Пловханы

- ~~Секции в `template_tasks` (`section: VARCHAR(64)`).~~ ✅ Готово:
  Alembic-ревизия `0006_template_section`, проброс через DTO/Pydantic/
  фронт. Экран смены группирует задачи по секциям с прогрессом и
  индикатором critical-pending.
- ~~Bulk-импорт чек-листа из текста (`POST /v1/templates/import`).~~ ✅
  Готово: парсер `bulk_parser.py` (`☐ ... / `## раздел`), dry-run-превью,
  юнит-тесты на текст Пловханы.
- ~~Авто-создание ежедневных смен через `default_schedule`.~~ ✅ Готово:
  `RecurrenceConfig`, валидация в `POST/PUT /v1/templates`, TaskIQ-периодик
  `recurring_shifts_tick` (каждую минуту), advisory-lock-идемпотентность,
  блок «Автосоздание смены» в редакторе шаблона.
- ~~Seed-скрипт `seed_plovkhana_templates.py`.~~ ✅ Готово:
  `make seed-plovkhana ORG="PlovХана"` создаёт шаблоны
  «Открытие ресторана» / «Закрытие ресторана» с критическими пунктами и
  recurrence на 09:00 / 23:00.

## V2 — Коммерциализация (недели 11–16)

- Биллинг: ЮKassa + Stripe, тарифы (Free, Pro, Business), trial 14
  дней.
- Миграция на Cloudflare R2: backfill-скрипт + переключение флага.
- Мультилокационный дашборд.
- Мобильные push'и через FCM (нотификации оператору перестают
  упираться в Telegram).
- Поле «причина задержки» при переработке.
- Запросы на обмен сменами.
- 90-дневное хранение фото с lifecycle-правилом R2.
- Экспорт по GDPR / 152-ФЗ + продакшеновые runbook'и erasure.

## V3 — Дифференциация (недели 17+)

- Нативные Flutter-приложения (iOS, Android) — Clean Architecture по
  внутренним правилам.
- AI-оценка фото (CLIP-эмбеддинги: чистая vs грязная барная стойка).
- Публичный REST API для интеграции с iiko / r_keeper.
- White-label-бот Telegram per-tenant (Enterprise-тир).
- Предиктивное планирование (предложение свапов на основе истории
  score).
- HR-надстройка: отслеживание производительности сотрудников во
  времени.

## Не-цели (пока не доказана необходимость)

- Управление складом (out of scope — есть в iiko/r_keeper).
- Интеграция с POS сверх импорта расписания (возможно в V3).
- Фичи «для гостей заведения» (это инструмент для персонала).
- Web-админка для не-админов (операторы остаются только в TWA).
