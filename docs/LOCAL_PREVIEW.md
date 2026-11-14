# Local Telegramless preview

## Назначение

`frontend/preview.html` — отдельный loopback-only preview Mini App для ручной проверки интерфейса без открытия Telegram.

В preview показывается явная synthetic-сессия (`LOCAL PREVIEW · TELEGRAM AUTH SIMULATED`), но это не настоящая Telegram-авторизация:

- нет Telegram SDK и `initData`;
- нет запросов к backend, БД, wallet ledger, PSP или Telegram;
- платежи, Stars, gifts и gift-card redemption отключены;
- данные и игровые сессии живут только в памяти вкладки и сбрасываются при обновлении.

Обычный `frontend/index.html` не меняет auth-политику: `/` без Telegram по-прежнему показывает `Abrir pelo Telegram`.

## Запуск

Из корня `frontend`:

```bash
npx --no-install serve . -l 8125
```

Открыть:

```text
http://localhost:8125/preview.html
```

`serve` может перенаправить clean URL на `http://localhost:8125/preview` — это тот же preview-entrypoint.

Не открывать через `file://` и не публиковать preview-файлы наружу. В production static deployment они исключены через `.vercelignore`.

## Что проверяется

- канонический каталог: 14 кейсов × 15 наград;
- WebP covers/rewards из `frontend/assets/demo`;
- synthetic balance, inventory, cases, daily reward и upgrade UI;
- Aprimorar с composite target keys, duplicate-rid targets, synthetic win/loss и без изменения wallet;
- Copos с production-уровнями: 3 → 3 → 4 → 4 → 5 → 5 стаканов;
- фиксированный synthetic шар на старте раунда;
- настоящий synthetic win/loss: неправильный стакан не начисляет баланс;
- Foguete: server-shaped start/status/cash, manual cashout, crash и idempotent terminal result;
- Mines/Foguete UI без live outcomes;
- отсутствие stale fullscreen modal/flash overlay при переходе между разделами.

Это закрытый визуальный стенд, а не разрешение принимать реальные платежи или подключать Telegram.
