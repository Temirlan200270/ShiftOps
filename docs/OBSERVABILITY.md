# Наблюдаемость

## Логи

- `structlog` в JSON для `staging` / `production`, pretty в `local`.
- У каждого запроса есть `request_id` (uuid4), внедряемый middleware'ом
  и связанный с контекстом structlog. Эхом возвращается в заголовке
  ответа `X-Request-ID`.
- Чувствительные поля (`Authorization`, `Cookie`, `init_data`)
  редактируются на уровне процессора.

## Метрики

Эндпоинт `/metrics` отдаёт стандартный Prometheus-экспозишн без
аутентификации (тело — агрегаты без PII; при необходимости можно
поднять Bearer-проверку, средствами Fly.io через приватную сеть или
доступ только из VPC).

Реализация — `prometheus-fastapi-instrumentator` для HTTP-уровня
(стандарт de-facto для FastAPI; даёт нам route-template
группировку и status-code группировку «из коробки») плюс собственный
модуль `shiftops_api/infra/metrics.py` для бизнес-метрик. Один файл
на все бизнес-счётчики — единственный источник правды и удобно
аудитить кардинальность.

Все кастомные метрики имеют префикс `shiftops_*`. Дефолтные имена
библиотеки оставлены без префикса (`http_requests_total`,
`http_requests_inprogress`) — так дашборды совместимы с любой
типовой Grafana-таблицей по FastAPI.

### HTTP-уровень (`prometheus-fastapi-instrumentator`)

| Метрика                          | Тип       | Лейблы                          | Назначение                                  |
| -------------------------------- | --------- | ------------------------------- | ------------------------------------------- |
| `http_requests_total`            | Counter   | `method`, `handler`, `status`   | QPS, error-rate (`status="5xx"`-доля).      |
| `shiftops_api_latency_seconds`   | Histogram | `method`, `handler`             | p50/p95/p99 латентности по роуту.           |
| `http_requests_inprogress`       | Gauge     | —                               | глубина очереди, ранний сигнал перегрузки.  |

`handler` — всегда **шаблон маршрута** (`/api/v1/shifts/{shift_id}`),
а не фактический URL. Так не взрывается кардинальность. Untemplated
запросы (404 на «дикие» URL) игнорируются (`should_ignore_untemplated=True`).
Status коды группируются в классы `2xx/3xx/4xx/5xx`
(`should_group_status_codes=True`). `/metrics`, `/healthz`, `/readyz`
исключены через `excluded_handlers`, чтобы не доминировали в дашбордах.

Имя `shiftops_api_latency_seconds` зафиксировано через
`metrics.latency(metric_name=...)` в `main.py` — это часть контракта
с Grafana-дашбордами, поэтому переименовываем только синхронно с ними.

### Бизнес-уровень (`infra/metrics.py`)

| Метрика                                          | Тип       | Лейблы                            | Где инкрементится                                        |
| ------------------------------------------------ | --------- | --------------------------------- | -------------------------------------------------------- |
| `shiftops_shifts_started_total`                  | Counter   | `location_id`, `template_id`      | `dispatch_shift_opened`                                  |
| `shiftops_shifts_closed_total`                   | Counter   | `location_id`, `status`           | `dispatch_shift_closed` (статус — `closed_clean`/...)    |
| `shiftops_tasks_completed_total`                 | Counter   | `criticality`                     | `dispatch_task_progress` (только `done`)                 |
| `shiftops_violations_total`                      | Counter   | `type`, `location_id`             | `dispatch_shift_closed` (`incomplete_required`, `late_close`) и `dispatch_task_progress` (`phash_collision`) |
| `shiftops_attachment_phash_collisions_total`     | Counter   | —                                 | `dispatch_task_progress` (если phash совпал)             |
| `shiftops_attachments_uploaded_total`            | Counter   | `provider`, `suspicious`          | `CompleteTaskUseCase` после успешной загрузки            |
| `shiftops_waiver_requests_total`                 | Counter   | `status`                          | `dispatch_waiver_request` (`open`) + `dispatch_waiver_decision` (`approved`/`rejected`) — единый funnel |
| `shiftops_waiver_decisions_total`                | Counter   | `decision`                        | `dispatch_waiver_decision` (legacy-зеркало того же события)|
| `shiftops_telegram_send_total`                   | Counter   | `method`, `result`                | `send_telegram_*` задачи (`ok`/`rate_limited`/`error`)   |
| `shiftops_telegram_send_duration_seconds`        | Histogram | `method`                          | те же задачи                                              |
| `shiftops_realtime_ws_connections`               | Gauge     | —                                 | live-monitor WS endpoint (inc на accept, dec на close)   |
| `shiftops_csv_import_rows_total`                 | Counter   | `outcome`                         | `ImportScheduleCsvUseCase` (`dry_run`/`created`/`error`) |

#### Таксономия `shiftops_violations_total`

Дискретные «нарушения правил», которые нам важны как KPI:

| `type`                  | Когда                                                                                               |
| ----------------------- | --------------------------------------------------------------------------------------------------- |
| `incomplete_required`   | На закрытии смены остался невыполненный required-таск (один инкремент на каждую такую задачу).       |
| `late_close`            | Смена закрыта более чем на 15 минут позже `scheduled_end` (порог совпадает с `score.timeliness`).   |
| `phash_collision`       | Загруженное фото перцептивно совпало с недавним. Дублирует `attachment_phash_collisions_total`, но даёт разрез по `location_id`. |

Critical-задачи в эту таксономию не попадают: `CloseShiftUseCase`
аппаратно блокирует закрытие при незавершённых critical, поэтому
`missed_critical` как тип *не наступает* в продуктовом потоке.

#### Funnel waiver-ов

`shiftops_waiver_requests_total` — единый счётчик с тремя
статусами (`open` → `approved | rejected`). В дашбордах считаем
approval-rate как
`sum(increase(...{status="approved"}[24h])) /
 sum(increase(...{status=~"approved|rejected"}[24h]))`.
Параллельный `shiftops_waiver_decisions_total{decision}` оставлен
для обратной совместимости и быстрых разрезов «что наклацал админ».

#### Бюджет кардинальности

При пилотном масштабе (≤10 организаций, ≤30 локаций каждая,
≤5 шаблонов на локацию) `location_id × template_id` даёт сотни серий
— безопасно. Если будем мульти-тенантить дальше — переезжаем на
recording rules (rollup без `location_id`).

## Healthchecks

- `/healthz` — liveness. Возвращает 200, если процесс жив. Под пробу
  liveness в Docker / Kubernetes.
- `/readyz` — readiness. Проверяет Postgres + Redis. Возвращает 503,
  если что-то лежит.

## Sentry

- DSN'ы — переменные окружения; не коммитим.
- Релиз тегается как `shiftops-api@<version>` / `shiftops-web@<version>`
  через GitHub Actions на push тега.
- `traces_sample_rate=0.1` по умолчанию; можно поднять per-route через
  теги Sentry.

## Дашборды

Лежат в `ops/grafana/` как JSON, портируемые через
`${DS_PROMETHEUS}`-вход. Подробности импорта — в `ops/grafana/README.md`.

- **`shiftops-operations.json`** — для дежурного: QPS, in-flight,
  p95 по роутам, 5xx-rate, отдельно Telegram delivery rate и его
  латентность.
- **`shiftops-business.json`** — для владельца: открытые/закрытые
  смены, задачи по criticality, доля phash-коллизий, нарушения по
  типам (`incomplete_required`/`late_close`/`phash_collision`),
  waiver-funnel и approval-rate, CSV-импорт.

## Scrape config (Grafana Cloud Agent / Alloy / vmagent)

```yaml
scrape_configs:
  - job_name: shiftops-api
    scrape_interval: 30s
    metrics_path: /metrics
    static_configs:
      - targets: ["api.shiftops.example:443"]
        labels:
          env: production
```

Для Fly.io можно поднять Grafana Agent отдельной machine'ой и читать
из `internal-shiftops-api.flycast:8080/metrics`.

## Алерты (минимум для пилота)

- Sentry-алерт: любое необработанное исключение → Telegram-канал `#ops`.
- Prometheus-алерт:
  `sum(rate(http_requests_total{status=~"5xx"}[5m]))
   / clamp_min(sum(rate(http_requests_total[5m])), 1e-9) > 0.01`
  10 минут подряд → пейджер дежурному.
- Prometheus-алерт:
  `sum(rate(shiftops_telegram_send_total{result="error"}[5m])) > 0.1`
  10 минут подряд → пейджер.
- Readiness-алерт: `up{job="shiftops-api"} == 0` или
  HTTP `/readyz` != 200 → немедленный пейджер.

### Worker / recurring tick алерты (RLS canary)

Файл с готовыми Prometheus rules лежит в `ops/alerts/shiftops-alerts.yml`:

- `ShiftOpsRecurringTickStalled`: воркер не обновлял gauge 10 минут (scheduler/worker умер).
- `ShiftOpsRecurringTickSeesZeroTemplates`: воркер 5 минут видит 0 шаблонов
  (типичный симптом сломанного privileged RLS bypass / grants).
