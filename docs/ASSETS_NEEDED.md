# Пул ассетов WINDROP — что приготовить и куда класть

Куда: **`roblox-case-platform/frontend/assets/`** (картинки, PNG/WebP, прозрачный фон),
`frontend/assets/sfx/` (звуки, ogg/mp3). Имена файлов — как в списке, подключение по имени.
Стиль: как у маскота — яркий неон-мультяшный на тёмном. Палитра: чёрный, красный #c8102e,
золото #ffb020, зелёный #2ecc71.

## 1. Кейсы (512×512, по одному файлу: `case_<badge>.png`)
brainrot (Steal a Brainrot), bloxfruits, growagarden, brookhaven, adoptme, 99nights,
rivals, dti (Dress to Impress), mm2, petsim99 + daily_fb / weekly_fb / mega_fb
(медные фрибет-коробки с бронзовой/зелёной рамкой).

## 2. Иконки типов предметов (128×128): `item_gp.png` (геймпасс/пропуск),
`item_perk.png` (плюшка/буст), `item_skin.png` (скин), `item_coin_copper.png` (медная монета).

## 3. Мини-игры
### Mines 💣
- фон решётки 512×512 (тайл), `mine.png` (мина с фитилем), `gem.png` (безопасная ячейка)
- `sfx: mine_tick.mp3` (тики), `mine_boom.mp3`, `mines_win.mp3`
### Crash 🚀
- `rocket.png` (ракета с огнём, 256×512), `crash_bg.png` (космос 1024×512, тайл по X)
- `sfx: crash_engine.mp3` (нарастающий гул), `crash_explode.mp3`
### Upgrade ⚡
- `upgrade_wheel.png` (колесо 512×512), `upgrade_arrow.png` (указатель)
- `sfx: upgrade_spin.mp3`, `upgrade_win.mp3`, `upgrade_lose.mp3`
### Shell 🥤
- `cup.png` (стакан 256×256), `ball.png` (шар)
- `sfx: shell_shuffle.mp3`, `shell_reveal.mp3`

## 4. Общие UI
- `logo_wide.png` (лого + надпись WINDROP, 1024×256) — для шапки и бота
- `bg_particles.png` (1024×1024 тайл, тёмный фон с неоном)
- конфетти-набор `confetti_01..08.png` (мелкие частицы для дропа Epic+)
- `glow_burst.png` (256×256 радиальное свечение для легендарки)
- иконка медной монетки `coin_copper.png` и золотой `coin_gold.png` (128×128)

## 5. Звуки общие (`sfx/`)
`spin_loop.mp3` (прокрутка кейса), `case_stop.mp3`, `win_big.mp3` (легендарка),
`coin_convert.mp3` (конвертация меди), `deposit.mp3`.

## Минимальный набор для запуска (если мало времени)
case_* (13 шт) + item_gp/perk/skin + mine.png + gem.png + rocket.png + spin_loop.mp3 +
case_stop.mp3 + win_big.mp3.
