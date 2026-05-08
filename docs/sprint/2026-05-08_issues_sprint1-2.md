# Sprint 1-2: 14 Issues (2026-05-08)

Список поступил от пользователя по итогам пилота. Разбит на два спринта.

---

## Sprint 1 — выполнено в этой сессии

| # | Задача | Файл(ы) |
|---|--------|---------|
| 9 | Поднять кнопку «Начать смену» выше | `dashboard-screen.tsx` |
| 5 | Лаг при возврате в приложение (проактивный рефреш токена) | `telegram-bootstrap.tsx` |
| 3 | Кнопка-галочка прямо на строке задачи | `task-list-screen.tsx` |
| 1 | Live Monitor → drill-down в смену (detail sheet) | `live-monitor-screen.tsx` |
| 10 | requiresPhoto = soft warning, не блокировать завершение | `task-detail-sheet.tsx` |
| 11 | Закрытие смены с причиной нарушения | `shifts.py`, `close_shift.py`, миграция, `task-list-screen.tsx` |
| 8 | История: добавить actual_start / actual_end timestamps | `history-screen.tsx` |

## Sprint 2 — следующая сессия

| # | Задача | Файл(ы) |
|---|--------|---------|
| 2 | Камера (Android) + ошибка загрузки фото | `task-detail-sheet.tsx`, CORS/Fly |
| 4 | Редизайн раздела «Команда» | `team-screen.tsx` |
| 6 | Сводка: наглядная аналитика (графики, KPI, тренды) | `analytics-screen.tsx` |
| 7 | Аудит: группировка, контекст, цвета | `audit-screen.tsx` |
| 12 | Настройки: язык, about, аккаунт | `settings-screen.tsx` |
| 13 | Фото с названием задачи в TG + daily digest | `telegram_storage.py`, `tasks.py` |
| 14 | Уведомления до/после смены | `tasks.py` |

---

## Заметки

- #1 drill-down в Sprint 1 показывает aggregate-данные из `ActiveShift` (без индивидуальных задач).
  Полный список задач потребует нового бэкенд-эндпоинта `GET /v1/admin/shifts/{id}/tasks` — Sprint 2.
- #11 `violation_reason` требует Alembic-миграции. Запустить `make migrate` перед деплоем API.
- #8 история не показывает closed shifts — причина скорее всего в отсутствии `actual_start/actual_end`
  в UI (данные в API уже есть). Не требует изменений на бэкенде.
