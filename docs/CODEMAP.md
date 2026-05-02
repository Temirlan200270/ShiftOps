# Карта репозитория ShiftOps

Тонкий ориентир **где искать код**, без полного перечня функций. Актуальная логика всегда в исходниках; этот файл нужно обновлять при крупных переездах папок или новых entrypoints.

См. также: [**CLAUDE.md**](../CLAUDE.md) (стек, команды), [**ARCHITECTURE.md**](ARCHITECTURE.md) (слои, диаграммы, ADR).

---

## Дерево верхнего уровня

```
apps/
  api/                    # Python API + воркер TaskIQ (тот же пакет shiftops_api)
  web/                    # Next.js TWA
infra/                    # Docker Compose, nginx
docs/                     # Продукт и эксплуатация (в т.ч. этот файл)
scripts/                  # seed, smoke
.github/workflows/        # CI/CD
```

---

## Где что лежит

| Нужно | Папка / зона |
|-------|----------------|
| HTTP-маршруты, Pydantic | `apps/api/shiftops_api/api/v1/` |
| Бизнес-сценарии | `apps/api/shiftops_api/application/` (по доменам: `shifts/`, `templates/`, `auth/`, …) |
| Чистая логика без IO | `apps/api/shiftops_api/domain/` |
| БД, бот, очередь, storage | `apps/api/shiftops_api/infra/` |
| Настройки окружения | `apps/api/shiftops_api/config/settings.py` |
| Миграции БД | `apps/api/alembic/` |
| Экраны TWA, UI | `apps/web/components/screens/` |
| Точка входа TWA (single route) | `apps/web/app/page.tsx` → `DashboardScreen` |
| Клиент API, сторы | `apps/web/lib/` |
| i18n | `apps/web/messages/` |

---

## Якорные файлы (старт поиска)

**API и приложение**

| Файл | Зачем |
|------|--------|
| [`apps/api/shiftops_api/main.py`](../apps/api/shiftops_api/main.py) | FastAPI app, middleware, подключение роутеров |
| [`apps/api/shiftops_api/api/v1/router.py`](../apps/api/shiftops_api/api/v1/router.py) | Сборка префикса `/v1`, включение всех роутеров |
| [`apps/api/shiftops_api/api/v1/shifts.py`](../apps/api/shiftops_api/api/v1/shifts.py) | Смены: me, claim, tasks, close, history, swap |
| [`apps/api/shiftops_api/api/v1/auth.py`](../apps/api/shiftops_api/api/v1/auth.py) | exchange initData → JWT, refresh |
| [`apps/api/shiftops_api/api/v1/realtime.py`](../apps/api/shiftops_api/api/v1/realtime.py) | WebSocket, снимок монитора (Эфир) |
| [`apps/api/shiftops_api/api/v1/analytics.py`](../apps/api/shiftops_api/api/v1/analytics.py) | Owner overview S9 |
| [`apps/api/shiftops_api/application/auth/deps.py`](../apps/api/shiftops_api/application/auth/deps.py) | `CurrentUser`, `require_user`, RLS-сессия |

**Очередь, периодики, уведомления**

| Файл | Зачем |
|------|--------|
| [`apps/api/shiftops_api/infra/queue.py`](../apps/api/shiftops_api/infra/queue.py) | TaskIQ broker (Redis) |
| [`apps/api/shiftops_api/infra/scheduling/tasks.py`](../apps/api/shiftops_api/infra/scheduling/tasks.py) | Cron: recurring shifts, vacant alerts, purge orgs, … |
| [`apps/api/shiftops_api/infra/notifications/dispatcher.py`](../apps/api/shiftops_api/infra/notifications/dispatcher.py) | Матрица TG: админ-чат, владелец, оператор |
| [`apps/api/shiftops_api/infra/notifications/tasks.py`](../apps/api/shiftops_api/infra/notifications/tasks.py) | `send_telegram_message`, media group |

**Telegram**

| Файл | Зачем |
|------|--------|
| [`apps/api/shiftops_api/infra/telegram/bot.py`](../apps/api/shiftops_api/infra/telegram/bot.py) | aiogram: `/start`, инвайты, waiver callbacks, deep links |
| [`apps/api/shiftops_api/api/v1/telegram.py`](../apps/api/shiftops_api/api/v1/telegram.py) | Webhook бота → dispatch updates |

**Фронт (TWA)**

| Файл | Зачем |
|------|--------|
| [`apps/web/app/page.tsx`](../apps/web/app/page.tsx) | Splash / onboarding / `DashboardScreen` |
| [`apps/web/components/screens/dashboard-screen.tsx`](../apps/web/components/screens/dashboard-screen.tsx) | Навигация по «экранам» без смены URL |
| [`apps/web/lib/auth/bootstrap-session.ts`](../apps/web/lib/auth/bootstrap-session.ts) | Handshake, refresh, гидратация сессии |
| [`apps/web/lib/api/client.ts`](../apps/web/lib/api/client.ts) | Обёртка fetch + JWT |

---

## Чего здесь нет намеренно

- Построчного списка классов и функций — дублирует IDE и устаревает за день.
- Описания каждого роутера из `api/v1/` — их много; смотри `router.py` и OpenAPI `/docs`.

При добавлении **нового вертикального среза** (например отдельный домен «биллинг») имеет смысл добавить сюда одну строку в таблицу «Где что лежит» и при необходимости один якорный файл.
