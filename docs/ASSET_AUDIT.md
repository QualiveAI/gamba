# Аудит ассетов каталога WINDROP

Дата проверки: 2026-11-11.

Проверка выполнена pure filesystem script без PostgreSQL, без запуска seed и без внешней сети. В UI порядок rewards определяется rarity-группой (`Herói → Lenda → Épico → Normal → Comum`), а внутри группы — стоимостью по убыванию; этот порядок не меняет server weights/chances. Регрессионный E2E fixture содержит намеренно инвертированные цены и подтвердил этот порядок. Источники: `backend/tools/demo_catalog.json`, `backend/tools/seed_demo.py`, `frontend/assets/demo/`, `frontend/assets/`.

## Матрица

| Группа | Кейсы | Предметов | Изображения | Covers |
| --- | ---: | ---: | ---: | ---: |
| Gold | 10 | 150 | 150/150 decodeable | 10/10 |
| Freebet/Cobre | 4 | 60 | 60/60 decodeable | 4/4 |
| **Всего** | **14** | **210** | **210/210** | **14/14** |

Проверенные freebet-кейсы:

- `trash` / Caixa do Lixo — 15/15;
- `daily` / Caixa Diária — 15/15;
- `weekly` / Caixa Semanal — 15/15;
- `monthly` / Caixa Mensal — 15/15.

Проверенные gold-кейсы:

- `brainrot`, `brookhaven`, `dti`, `garden`, `nights`, `rivals`, `mm2`, `adopt`, `blox`, `pets` — каждый 15/15.

## Что было найдено

В canonical JSON осталось 21 `image: null`:

- `dti8`, `garden9`, `nights11`, `pets7`, `trash15`;
- `daily11`, `daily13`, `daily15`;
- `weekly6`, `weekly7`, `weekly8`, `weekly10`, `weekly11`, `weekly15`;
- `monthly6`, `monthly7`, `monthly8`, `monthly11`, `monthly13`, `monthly14`, `monthly15`.

Для всех 21 ключей нормализованный `frontend/assets/demo/<asset>.webp` уже существует. `fix_missing_images()` подставляет его в память перед seed, а новая проверка убеждается, что API seed не оставляет этот пробел. Для серий с исходниками пользователя добавлен canonical source fallback (`99ночей*`, `дти*`, `гроугарден*`, `петсим*`, `мусор*`, `день*`, `неделя*`, `месяц*`) на случай отсутствия нормализованного WebP.

Результат чистой проверки: `bad=0`, `null_after_fix=0`; все найденные изображения открываются Pillow `Image.verify()`. Shared Robux assets считаются допустимым переиспользованием, а не пропавшим ассетом.

## WebP optimization

Нормализованный набор из 181 WebP был обработан локальным `backend/tools/optimize_demo_webp.py` в отдельный staging-каталог с quality=82/method=6. Декодирование, размеры и alpha были проверены; исходные PNG/JPG masters не трогались. После проверки staging заменил только normalized `frontend/assets/demo/*.webp`: 6,091,832 → 4,440,690 bytes (**−27,1%**). Прозрачные `logo-mark`/`windrop-symbol` также имеют WebP-копии, а landing/Mini App используют их для уменьшения первого запроса.

Временно созданный manifest staging не является production secret и не добавляется в репозиторий.

## Browser preview

В локальном mock Mini App на `127.0.0.1:8125/app/` через browser-use проверены все 14 case records из preview API: 14/14 cases, 210/210 rewards и `null image=0` после применения fallback. DOM отдельно показал gold cards и все четыре freebet tabs: `Caixa do Lixo`, `Caixa Diária`, `Caixa Semanal`, `Caixa Mensal`. Для visible gold preview и freebet preview повторная загрузка каждого URL через page-local `Image` дала `naturalWidth > 0` и `naturalHeight > 0`; failed=0. Lazy-режим не трактуется как пропавший asset: для проверки использована отдельная decode-проверка URL.

## Ограничения

- `frontend/assets/demo/` содержит 181 WebP: это нормализованный набор с переиспользованием общих предметов, не обязан быть 210 уникальными файлами.
- Legacy `backend/tools/seed_cases.py` содержит старый отдельный каталог и не используется новым demo API; его не следует запускать поверх production catalog.
- Реальная PostgreSQL seed не запускалась в этом аудите; проверен только pure filesystem resolution. Перед изменением БД нужен отдельный изолированный migration/seed run.
- Browser DOM-проверка всех 14 карточек требует запущенного mock/API preview и выполняется отдельно; текущий pure audit не подменяет browser screenshot.
