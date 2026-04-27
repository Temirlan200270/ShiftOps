# Формула оценки смены

Score — число в диапазоне `[0, 100]`, записываемое в `shifts.score` на
закрытии смены.

## Формула

```
score = 100 * (
    0.50 * completion +
    0.25 * critical_compliance +
    0.15 * timeliness +
    0.10 * photo_quality
)
```

### `completion`

```
done_count / total_count
```

Где `done_count` включает `done` и `waived` (одобренные waiver'ы не
штрафуют). `skipped` и `waiver_rejected` считаются не выполненными.

### `critical_compliance`

```
1.0, если все критические задачи выполнены или waived
0.0 иначе
```

Намеренно булева: пропуск критической задачи топит оценку.

### `timeliness`

```
1.0, если actual_end <= scheduled_end
линейное снижение до 0 за окно переработки в 2 часа
```

```python
delay = max(0, (actual_end - scheduled_end).total_seconds())
timeliness = max(0, 1 - delay / (2 * 3600))
```

### `photo_quality`

```
photos_unique / photos_total
```

Где `photos_unique` — число вложений с `suspicious = false`. Задачи без
требования фото не входят ни в числитель, ни в знаменатель.

## Примеры

- Смена на 20 задач, все выполнены, в срок, без подозрительных фото
  → 100.0.
- Та же смена, пропущена 1 required → completion = 0.95, score = 97.5.
- Та же смена, пропущена 1 critical → critical_compliance = 0 → score
  = 70.0 (50 + 0 + 15 + 10 − 5 = 70).
- Та же смена, в срок, 2 из 8 фото подозрительны → score = 97.5.

## Гарантия стабильности

Формула версионирована (`SCORE_FORMULA_VERSION = 1` в API). Когда в V2
её поменяем — исторические смены сохранят свой исходный score; новые
смены посчитаются по новой версии. Это исключает «плавающее» прошлое у
сотрудников, что политически токсично.
