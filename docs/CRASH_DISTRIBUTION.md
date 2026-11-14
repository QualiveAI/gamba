# Crash / Foguete: текущий математический контракт

## Статус

Crash пока не считается готовым для real-money запуска: в репозитории есть legacy/plugin paths с другими RTP и modifiers, а полноценный commitment/reveal server seed ещё не подключён. Этот документ описывает только новый `app.games.crash` start/cash flow.

## Новый flow

- `POST /games/crash/start` получает только ставку.
- Сервер один раз генерирует roll и сохраняет рассчитанный `crash_point` в `crash_sessions`.
- Клиент не выбирает точку взрыва и не генерирует outcome.
- `POST /games/crash/cash` повторно проверяет владельца, статус сессии, DB server time и `crash_point` под row lock.
- `GET /games/crash/status` позволяет восстановить состояние после потерянного HTTP-ответа/скрытия вкладки и materializes an expired active round as busted.
- Повторный cashout terminal-сессии возвращает сохранённый результат и не создаёт вторую выплату.

Текущий pure mapping:

```text
crash_point = clamp(round(SESSION_RTP / (1 - roll), 2), 1.0, MAX_MULT)
SESSION_RTP = 0.97
MAX_MULT = 1000
```

Ощущение частых малых крашей не следует исправлять скрытым смещением под игрока. Распределение и RTP должны быть утверждены как единая математика, а вариант с визуальным минимумом/кусочным hazard требует отдельного расчёта, payout/RTP тестов и прозрачного disclosure до включения. Текущий patch выносит mapping в pure function, но не объявляет live-ready fairness/commitment.

Для фиксированного cashout x ожидаемая выплата до округления примерно `0.97 × ставка`, а вероятность достижения x примерно `0.97 / x`. Поэтому маленькие точки встречаются чаще, а большие — редко, но хвост существует. Это случайное распределение, не гарантия конкретного результата отдельного игрока.

Ориентиры для проверки:

- около 51.5% точек ниже x2;
- около 32.3% достигают x3 или выше;
- около 9.7% достигают x10 или выше;
- около 0.97% достигают x100 или выше.

Округление и cap дают небольшие отклонения; CI использует deterministic sequence и интервалы, а не один случайный раунд.

## Запреты

Outcome не должен зависеть от `user_id`, ставки, streak, loss history, segment, Redis chase counter или admin override. Промо/компенсации должны идти отдельным прозрачным ledger-потоком, а не изменять crash point.

## Открытые блокеры

- `crash_sessions` ещё не хранит server-seed commitment/reveal fields; текущий flow нельзя независимо проверить игроком после раунда.
- Legacy `POST /games/crash` и plugin Crash имеют отдельные формулы/metadata и должны быть закрыты, объединены или явно ограничены dev/test перед live.
- `SESSION_RTP`/frontend/docs legacy values требуют единого production approval.
- Требуются статистические fixed-threshold RTP, independence, concurrency и commitment/reveal tests на изолированной БД.
