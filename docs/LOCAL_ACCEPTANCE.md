# WINDROP — локальная приёмка

Дата: **2026-11-11**. Ветка `windrop-wip`, незакоммиченная рабочая реализация поверх `de4dca9`. Этот документ фиксирует локальные проверки, **не разрешение принимать реальные деньги**.

## Что реализовано

- Серверные immutable-котировки, единый payment intent, идемпотентность, durable inbox и атомарные ledger/status/outbox; раздельные целые монеты, BRL centavos, XTR и crypto atoms.
- Четыре канала с явными выключателями: Stars, Telegram Gifts, карты и криптовалюты. Локальная симуляция не зачисляет расходуемые монеты. Необходимые внешние доказательства не подменены моками.
- Основной бот и персональные Managed Bots: общий аккаунт, ownership/credential checks, main-only Stars, шифрованный inbox, отдельные webhook secrets, очередь доставки.
- Склад заранее полученных Roblox/BR gift cards: encrypted codes, SKU/номинал отдельно от цены в монетах, атомарное назначение/списание, повторная доставка того же кода, запрет автоматического возврата в склад после начала отправки.
- Интеграция frontend без замены выбранного визуального языка; отдельный внешний PT-BR лендинг; конфигурации primary/standby, readiness, отдельные scheduler и workers.
- PT-BR localization layer для 14 кейсов и 210 лут-названий; player API/инвентарь используют локализованные display labels, технические game keys и экономика не меняются.
- Asset audit: 10 gold + 4 freebet cases, 210/210 item images и 14/14 covers проходят filesystem/decode проверку; browser preview отдельно подтвердил четыре freebet cards и 16 URL decode с `naturalWidth > 0`. См. `docs/ASSET_AUDIT.md`.
- Бесплатный backend вариант описан в `docs/FREE_BACKEND_OPTIONS.md`: Vercel static, Oracle Always Free VM как $0-ish always-on candidate, sleeping services только preview, external Postgres/Redis с лимитами.
- Production UI не показывает технические `DEMO`/`Demonstração`/`sandbox`-подписи; внутренние sandbox guards и test fixtures сохранены.
- Добавлен `vercel.json` и `docs/VERCEL_FREE.md`: Vercel только static/edge для landing и Mini App; durable API/workers/DB/Redis/media остаются внешними.

Подробности: [платежи](PAYMENT_INTEGRATION.md), [Managed Bots](BOT_POOL.md), [гифт-карты](GIFT_CARD_REDEMPTION.md), [ассеты](ASSET_AUDIT.md), [бесплатный backend](FREE_BACKEND_OPTIONS.md), [лендинг](LANDING.md), [развёртывание](DEPLOYMENT.md), [восстановление](RESTORE.md), [публичные источники и ограничения провайдеров](PROVIDER_RESEARCH.md).

## Изоляция

- Обычные pytest используют только `windrop_test` и ограниченную роль с таким же именем в отдельном PostgreSQL на `127.0.0.1:55432`; Redis — отдельный порт `56379`, логическая БД 15.
- `TEST_DATABASE_URL` обязателен до импорта приложения. Guard проверяет имя/роль `*_test`, запрет superuser/создания ролей и доступа к другим non-template БД; test collection не запускает старые очистки.
- `WINDROP_TESTING=1` исключает чтение `.env`. Реальный HTTP transport в тестах блокируется; используются ASGI/MockTransport.
- UI sandbox имеет отдельную `windrop_preview_test`, синтетический Telegram SDK/пользователя и только `TEST-ONLY` карты. Его данные не очищаются pytest.
- Рабочие `infra-*`, PostgreSQL `5432`, Redis `6379`, API `8001`, сайт `8090` и чужой сервис на `8000` не перезапускались и не мигрировались в этом этапе. Исходный frontend bind-mounted в старый стек, поэтому `8090` нельзя считать обновлённым end-to-end backend.
- Реальные `.env`, bot tokens, дампы, коды карт и seed кошелька для проверки не читались. Новых commit/push, регистрации поставщиков, покупок, публикации и production switch не было.

## Автоматические проверки

| Проверка | Результат | Что доказывает |
| --- | --- | --- |
| Полный `pytest backend/tests -q` | **269 passed**, 10.37 s, exit 0 | Локальные SQL/ASGI/MockTransport-регрессии; включая деньги, ownership, outbox, склад, scheduler |
| `python -m ruff check backend` | `All checks passed!` | Статический анализ |
| `python -m ruff format --check backend` | `287 files already formatted` | Форматирование текущего backend |
| Frontend Node tests | **38 passed**, 0 failed | Клиентские контракты, auth retry, quote/order state, safe links/storage |
| Landing Node tests | **23 passed**, 0 failed | UTM/username allowlist, локальные assets, no-network defaults, disclaimers |
| Frontend + landing Node одной командой | **61 passed**, 0 failed | Сводный локальный клиентский gate |
| Playwright Chromium, полный новый набор | **23 passed**, 0 failed, 0 skipped; 26.6 s | UI с подменёнными Telegram SDK/API, не реальные Telegram/PSP |
| После локализации, asset audit и сортировки | **61 Node passed; 23 E2E passed** | PT-BR display labels, 14×15 asset matrix, rarity-first/value-desc order, отсутствие visual test markers, сохранённые payment guards |
| JS/CJS syntax checks | passed | Парсинг frontend/landing/test modules |
| `infra/drill` Ruff + format + py_compile | passed; 2 files formatted | Статическая готовность изолированного failover harness; сам drill требует Docker |
| CI YAML | parsed, оба jobs найдены | Только локальная проверка YAML; GitHub Actions не запускался |
| Compose local/prod/failover | config validation passed | Синтаксис/интерполяция с явным пустым env; не production deployment |
| Caddy prod/failover | `validate`: valid, network none | Синтаксис конфигураций; format warnings не ошибки |
| Bash backup/restore | syntax passed | Не доказательство работоспособности age/offsite backup |
| Каталог/ассеты/логотип | 14×15=210 предметов, 210/210 decodable item images, 14/14 covers; demo WebP −27.1%, RGBA preserved | Pure filesystem + browser asset checks; WebP optimized, прозрачность сохранена |

### Ошибки, найденные и исправленные в финальном проходе

1. Первый format gate вернул exit 1: девять файлов требовали форматирования. Исправлены только эти файлы; AST до/после совпал у 9/9. После этого Ruff checks прошли.
2. Первый новый полный E2E-набор дал 16/16. Добавленные пять регрессий воспроизвели активные кнопки приглашения при missing/invalid/stale ссылке, доверие к изменённому DOM-полю и перекрытие названия балансами на 388 px. После исправлений проверки прошли.
3. Отдельная регрессия воспроизвела raw ledger reasons в истории. Добавлены PT-BR подписи для обмена, Welcome и явно обозначенного тестового баланса. Итоговый E2E-набор — 23/23.
4. Регрессия с остановленными animation frames воспроизвела первоначальный нулевой chip баланса. Начальный wallet теперь рисуется без ожидания animation frame; отдельный E2E проверяет gold/copper сразу после загрузки.
5. В seed переводов оставалось шесть русских названий. Добавлены точные переводы и тест всех 210 labels; цены, веса, assets и экономические значения не менялись. В существующей preview БД обновлены только соответствующие шесть подписей, не запускался полный seed; рабочая БД не менялась.
6. `/referrals/my` без `BOT_USERNAME` возвращает безопасный 503 вместо 500; интерфейс больше не предлагает копировать или отправлять отсутствующую ссылку.
7. Production config теперь отклоняет sandbox payment/gift-card modes; sandbox-settle endpoint закрыт вне dev/test; live history фильтрует test-only ledger reasons.

Новые E2E запускают собственную статику только на 8123, `reuseExistingServer=false`; разрешены локальные ресурсы и замоканный SDK, незаявленные внешние URL блокируются. Использованы уже установленные Playwright 1.64.1/Chromium 1248, без загрузок пакетов или браузеров. Firefox/WebKit не запускались. Последующее изменение index cache-buster `v14 → v15` не меняет JS/CSS; logo hash сохранён.

В `.github/workflows/ci.yml` добавлен отдельный frontend job: Node 24, lockfile-based install, unit/landing checks и Chromium E2E. Его будущая установка зависимостей выполняется только при обычном разрешённом запуске GitHub Actions; локальная работа CI не публиковала.

## Настоящий локальный API через браузер

Проверено official browser-use на `http://127.0.0.1:8125/app/`; это **реальное приложение и PostgreSQL с синтетическими данными**, а не тест реального Telegram.

- Котировка 100 монет: BRL 810 centavos net + 162 fee = **R$ 9,72**. Создан один канонический intent.
- Явное завершение sandbox изменило статус на `sandbox_succeeded`, сохранило отдельное sandbox-событие. Баланс остался **5000 gold / 2000 copper**, расходуемый кредит не появился.
- Обмен на тестовый SKU номиналом **R$ 50,00** и ценой **1000 монет** создал один заказ и назначил одну карту. Баланс стал **4000 / 2000**; в outbox только ссылка на redemption, без кода.
- Заказ остался pending, потому что реальная Telegram-доставка намеренно отключена. Внешнее сообщение не отправлено, настоящий код не выдан.
- Мобильные формы, статусы sandbox, недоступный Managed Bot CTA, каталог и прозрачная эмблема просмотрены. Lazy images проверены после загрузки, а не признаны пропавшими по первому незавершённому кадру.
- Лендинг `http://127.0.0.1:8124/` проверен на мобильной ширине 390 px. Исправлено наложение трёх case images на заголовки, подтверждён зазор 22 px; горизонтального переполнения нет. CTA с пустым username открывает локальное объяснение, `Esc` закрывает диалог.

Ограничение: нет полного accessibility/кросс-браузерного аудита, всех размеров 360–1440 и реальных клиентов Telegram. API-моки в E2E и синтетический browser sandbox отделены от PSP/Telegram staging.

## Восстановление синтетической БД

В отдельную пустую `windrop_restore_test` выполнен настоящий `pg_dump`/`pg_restore` preview-состояния без owner/ACL и без `--clean`. На диск записывался только Fernet ciphertext. Сравнены данные:

| Объект | Совпало строк |
| --- | ---: |
| users | 1 |
| ledger | 4 |
| payment intents | 1 |
| redemptions | 1 |
| outbox | 1 |
| inventory | 2 |
| schema migrations | 18 |

Сумма ledger совпала с обоими балансами. Рабочие данные не использовались. Это пробное восстановление синтетических данных, **не проверенный постоянный backup**: ключ Fernet был временным, age binary отсутствует, `infra/backup.sh`/`restore-test.sh` end-to-end с age не запускались. Offsite retention, PITR, disaster recovery ключей и production restore остаются отдельной работой.

## Переключение приложения и восстановление worker

В изолированном target `windrop_failover_retry_test` был выполнен drill без live Telegram/PSP: migrations=18, первичный API отвечал, переключение primary→standby заняло **1,76 s**, повторный redemption через standby вернул тот же order, balance остался 863 и debit/outbox были по одному. После SIGKILL worker-а fake sink принял сообщение до DB receipt; естественный lease=180 s был выдержан (**176,03 s** до reclaim), повторно ушёл тот же digest: 2 synthetic sends, 1 distinct card message, 1 issued card, 1 debit. Повторный webhook пять раз дал 1 inbox row и 1 command outbox row; primary failback также прошёл.

Этот запуск **не засчитывается как полный pass**: после остановки обоих API финальный запрос через internal controller получил `ReadTimeout` до того, как harness преобразовал недоступность в ожидаемый HTTP 503. Поэтому `both_apis_down_status` и `status=passed` в артефакте отсутствуют. Harness исправлен: internal controller теперь возвращает синтетический 503 на недоступный endpoint; `infra/drill` форматирован и проходит Ruff. Повторить после восстановления Docker Desktop необходимо именно для закрытия последнего assertion. Тестовый Docker daemon сейчас недоступен (`npipe ... dockerDesktopLinuxEngine not found`), поэтому результат не подменяется ручным утверждением.

Репетиция использовала отдельную `*_test` БД, internal Docker network, synthetic keys и fake sink; live Telegram не вызывался. Созданные drill-контейнеры остановлены, рабочие `infra-*`, 8000/8001/8090 и production данные не использовались.

## Что блокирует реальный запуск

- Paymento: нет подключённого production HTTP transport/create order и авторитетной привязки crypto destination/merchant settings. PayGate: неподписанного GET callback недостаточно; независимая доверенная сверка не подключена. **Live card/crypto остаются выключенными**, ключи сами по себе их не включают.
- Отсутствие KYC во всей цепочке фиат→крипта не подтверждено. PIX/BRL, допустимость продукта у PSP/площадок, требования покупателю/оператору требуют отдельного подтверждения; обход проверок не реализован.
- Реальные BotFather manager capability, создание личного бота, смена владельца/токена и Stars invoice/refund в настоящем Telegram не проверялись. Личный бот игрока не получает main/admin/merchant trust.
- Gifts: только контролируемая ручная аттестация и оценка, автоматический business receipt/custody importer не подключён. Не обещается конвертация любого подарка.
- Для неизвестного результата Stars refund (`processing/unknown`) нет полной автоматической сверки и операторского UI разрешения. Слепой повтор запрещён.
- Нет договора/закупки у оптового поставщика, подтверждения Roblox BR SKU и прав распространения; нет автоматической supplier reconciliation, проверки активации, key rotation и решения giftcard manual review. Legal landing copy — черновик.
- **Игровое ядро не прошло аудит для real money.** Старые Crash/Shell раскрывают результат клиенту/используют предсказуемые параметры; legacy Mines требует отдельной проверки ownership/locking и механики переразмещения мин; upgrade доверяет пользовательским параметрам цели. Зелёные платёжные/UI-тесты не устраняют эти ограничения. В этом этапе игровую экономику и исходы не перерабатывали.
- Не выполнены cloud deployment, production migration/switch, DB promotion, PITR/offsite age-drill, object storage. Резерв приложения не означает безопасное автоматическое создание второго writable PostgreSQL. Ротация Vercel-аккаунтов для обхода блокировок не реализована.

## Команды повторной проверки

Из корня репозитория, **только с заранее подготовленной изолированной БД**:

```bash
TEST_DATABASE_URL='<явный DSN отдельной *_test БД и роли>' \
TEST_REDIS_URL='<явный URL отдельного тестового Redis>' \
python -m pytest backend/tests -q
python -m ruff check backend
python -m ruff format --check backend
node --test frontend/tests/unit/*.test.cjs
node --test landing/tests/landing.test.cjs
```

Из `frontend/`, только с уже установленными зависимостями и свободным портом:

```bash
E2E_PORT=8123 npx --no-install playwright test --reporter=line
```

Не использовать рабочий DSN, старые очищающие скрипты или автоматическое чтение `.env` ради запуска проверок. Нет необходимости пересоздавать пользовательские балансы после тестов.
