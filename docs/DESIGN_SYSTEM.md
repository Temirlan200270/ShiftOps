# Дизайн-система — ShiftOps

> «Linear для баров». Премиальный тёмный, glass-поверхности, тихая
> анимация. Бармен должен чувствовать, что пользуется prosumer-инструментом
> за 20$/мес, а не корпоративной анкетой.

## Источник правды и референс

| Что | Где |
|-----|-----|
| **Прод TWA** | Токены в [`apps/web/app/globals.css`](../apps/web/app/globals.css) как CSS-переменные (HSL-триплеты) → Tailwind в [`apps/web/tailwind.config.ts`](../apps/web/tailwind.config.ts). |
| **Интерактивный макет** | [`shiftops-demo.html`](shiftops-demo.html) — один HTML-файл с локальным роутером и **мок-данными**. Используйте для визуального согласования и копирайта; **не** копируйте оттуда логику, дублирование API или CDN-стек в приложение. |
| **Сценарии и состояния** | [`UX_FLOW.md`](UX_FLOW.md) — конечные автоматы и edge cases. |

Палитра семантики (primary / success / warning / critical) совпадает с макетом в `shiftops-demo.html`. Фон приложения: **чёрный + мягкий radial** (как в демо), карточки — нейтральные «neo-noir» поверхности без сине-серой дымки прежнего `#0B1220`.

## Токены

### Цвет

Реализация в коде — переменные `--bg`, `--surface`, `--elevated`, `--foreground`, `--primary`, … Ниже ориентиры в Hex для спеки и макетов.

| Токен (концепт) | Hex (ориентир) | В TWA / Tailwind |
| - | - | - |
| Страница (база) | `#000000` | Фон `body`: чёрный + `radial-gradient` (см. `globals.css`); при необходимости сплошной заливки — `background` / `--bg` |
| Карточка / surface | `#12121a` → `#0a0a0e` градиент в демо | `bg-surface` → `--surface` |
| Поднятая зона / sticky | чуть светлее surface | `bg-elevated` → `--elevated` |
| Border hairline | `rgba(255,255,255,0.06)` | `--border` |
| `primary` | `#4F7CFF` | CTA, активные состояния, фокус-кольцо |
| `primary` (hover, вариант) | `#3E63DD` | Hover/pressed CTA в компонентах |
| `success` | `#30A46C` | Положительные состояния, галочки |
| `warning` | `#F5A524` | Предупреждения, «похоже на прошлое фото» |
| `critical` | `#E5484D` | Критические задачи, ошибки |
| Основной текст | `#F8FAFC` | `text-foreground` / `--fg` |
| Вторичный / muted | `#CBD5E1` / `#94A3B8` | `text-muted-foreground` / `--muted-fg` |

Контрастные цели: WCAG AA, минимум 4.5:1 на основном тексте. В исходной
Figma подзаголовок имел 2.7:1 — починен в `text-secondary`.

### Типографика

- **Семейство:** `Inter` для UI, `JetBrains Mono` для моноширинных
  (таймстемпы, ID, хеши).
- **Размеры:** 12 / 14 / 16 / 20 / 28 / 36 — отношение 1.25.
  CSS-переменные: `--text-xs`, `--text-sm`, `--text-base`, `--text-lg`,
  `--text-2xl`, `--text-4xl`.
- **Начертания:** 400 (body), 500 (UI), 600 (titles), 700 (display).
- **Line-height:** 1.4 body, 1.2 titles.
- **Letter-spacing:** `-0.01em` на `body` (как в макете-демо), у заголовков
  можно ужесточать до `-0.04em`; 0.06em для allcaps-лейблов.

### Шкала отступов

`4 / 8 / 12 / 16 / 24 / 32 / 48`. Токены `app-1..app-7` в Tailwind-конфиге.

### Радиусы

- 8 (чипы, бейджи).
- 12 (инпуты, маленькие карточки).
- 16 (карточки, шторки, основные поверхности).
- 24 (нижние шторки, углы модалок).
- 9999 (аватары, pill'ы).

### Elevation / тени

- `shadow-sm`: `0 1px 2px rgba(0,0,0,0.4)` — hairline на тёмных
  поверхностях.
- `shadow-md`: `0 8px 24px rgba(0,0,0,0.4)` — модалки, дропдауны.
- `shadow-glow-primary`:
  `0 0 0 1px rgba(79,124,255,0.4), 0 0 24px rgba(79,124,255,0.25)` —
  фокус-кольцо на CTA.
- `shadow-glow-critical`: то же, но в critical-цвете.

### Анимация

- Длительности: 120 (микро), 200 (default), 320 (открытие шторки).
- Easing: `cubic-bezier(0.32, 0.72, 0, 1)` («soft snap» в духе Apple).
- Никакого bounce. Никаких бесконечных спиннеров дольше 3 с — вместо
  них скелетон.

### Haptics

TWA SDK даёт `HapticFeedback`. Конвенции:

- `impactOccurred('light')` — задача отмечена.
- `impactOccurred('medium')` — основной CTA (Start, Done).
- `impactOccurred('heavy')` — необратимое действие (Close shift).
- `notificationOccurred('error')` — провал валидации.
- `notificationOccurred('success')` — смена закрыта чисто.

## Компоненты (на базе shadcn/ui)

- **Button** — размеры `sm 36px / md 44px / lg 56px`. `lg` — touch-цель
  для основных CTA (защита от «жирных пальцев»). Варианты:
  `primary | secondary | ghost | destructive`.
- **Card** — glass-поверхность, радиус 16 px, бордер 1 px, паддинг
  16 px по умолчанию.
- **Sheet** — нижняя шторка для деталей задачи / waiver. Drag-handle.
  Snap'ы 50% / 100%. Backdrop blur, закрытие тапом по фону.
- **Toast** — справа сверху на десктопе, по центру сверху на мобиле.
  Авто-закрытие 4 с. Варианты: success / warning / critical.
- **ProgressBar** — sticky на экране смены. Анимируется только на
  увеличении — чтобы не «дёргался».
- **Badge** — для critical и статусов. Critical = красный заполненный,
  Required = синий outlined, Optional = zinc outlined.
- **TaskCard** — Card + иконка + title + бейдж статуса. У critical-варианта
  4-пиксельный левый бордер цвета `critical`.
- **CaptureZone** — drop-зона 240×240 с дэшедным бордером, иконкой
  камеры и подсказкой. По нажатию → срабатывает
  `<input capture="environment">`.

## Иконки

- `lucide-react`, line-иконки, обводка 1.5 px, по умолчанию 24 px.
- Допустимые отклонения: брендовые (логотип Telegram на кнопке
  «поделиться ссылкой»).

## Тон и копирайт

- **Тон:** прямой, профессиональный, восклицательные знаки только в
  success-toast'ах.
- **Длина:** текст на кнопке ≤ 20 символов, ошибки ≤ 80 символов.
- **Двуязычность:** каждая строка живёт в `messages/{ru,en}.json` и
  идёт через `next-intl`. **Никогда** не хардкодим русский или
  английский в компонентах.
- **Регистр:** Sentence case, не Title Case. Русский — тоже
  sentence case: «Начать смену», не «Начать Смену».

## Промпты для генерации UI

### Список активной смены

> High-end mobile SaaS UI, near-black bg #000000 with subtle top radial glow,
> cards on dark neutral surface (~#12121a), border 1px rgba(255,255,255,0.06),
> vibrant accent #4F7CFF.
> Sticky progress bar 65% top. Three sections: Critical (red 4px left
> border), Required, Optional. Task card has line icon (camera/check), title
> 16px Inter Medium, status badge, chevron. Disabled FAB bottom 'Close shift'
> with tooltip 'Complete 3 critical tasks'. Linear/Stripe aesthetic, 16px
> radius, soft shadows, no gradients on text.

### Деталь задачи со съёмкой

> Mobile task detail screen, dark glassy style, large 240×240 capture zone
> with camera icon and 'Camera only — gallery disabled' hint, photo preview
> with 'Unique image ✓' green badge or 'Similar to last shift ⚠' amber
> badge, comment field, sticky primary 56px button 'Done'. Inter font, 16px
> radius, fintech-grade polish.

### Аналитика собственника

> Mobile dashboard, donut chart shift score 87%, top-3 violators list with
> avatars, heatmap 7×24 task completion times, all in dark glassmorphism cards
> on near-black #000000, Inter, electric blue primary #4F7CFF, similar to Linear
> Insights.
