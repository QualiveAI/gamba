"""Сид кейсов WINDROP v6: 15 предметов в каждом кейсе.

Тиры: 5 мусор / 4 обычка / 3 эпик / 2 легендарки / 1 герой(джекпот).
Шансы группы: 80/15/4.5/0.499/0.001 (веса: 16/3.75/1.5/0.2495/0.001).
Предметы сортируются по цене; недостающие добираются универсальными паками робуксов.
Фрибет-кейсы (медь): Lixo 50, Diária 250, Semanal 375 (streak>=7), Mensal 500 (streak>=30).

Запуск: python tools/seed_cases.py  (без -I: user site-packages)
"""

import os
from pathlib import Path

import psycopg

DSN = os.getenv(
    "DATABASE_URL",
    next(
        line.split("=", 1)[1].strip()
        for line in (Path(__file__).resolve().parent.parent / ".env")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.startswith("DATABASE_URL=")
    ),
)

TIER_W = [16.0] * 5 + [3.75] * 4 + [1.5] * 3 + [0.2495] * 2 + [0.001]
ROBUX_PACKS = [(10, 13), (25, 30), (50, 62), (100, 120), (150, 180), (250, 300), (1000, 1300)]


# Кейсы: имя -> (бейдж, цена, [(название|тип, цена руб)])
CASES = {
    "Brainrot Case": (
        "brainrot",
        99,
        [
            ("10 Робуксов|cash", 13),
            ("Титул «Из Огайо»|perk", 15),
            ("Банка Grimace Shake|perk", 10),
            ("Питомец «Кот Максвелл»|skin", 25),
            ("Скин «Вантуз Скибиди»|skin", 30),
            ("50 Робуксов|cash", 70),
            ("Эмоция «Мьюинг»|perk", 100),
            ("Бустер «Сигма-Фокус»|perk", 80),
            ("Питомец Шайлушай|skin", 120),
            ("250 Робуксов|cash", 300),
            ("Аура «Brainrot»|skin", 450),
            ("Питомец «Гигачад Доге»|skin", 500),
            ("1 000 Робуксов|cash", 1300),
            ("Маунт Bing Chilling Dragon|skin", 1900),
            ("ДЖЕКПОТ: 5 000 Р$ + Абсолютный Сигма|gp", 9000),
        ],
    ),
    "Brookhaven Case": (
        "brookhaven",
        199,
        [
            ("Базовый самокат|skin", 40),
            ("Роликовые коньки|skin", 45),
            ("Пасс на лица|gp", 200),
            ("Ховерборд|skin", 220),
            ("Пасс на бассейн|gp", 350),
            ("Пасс на дома|gp", 450),
            ("Пасс на премиум авто|gp", 1500),
            ("ДЖЕКПОТ: VIP + 10k|gp", 12000),
        ],
    ),
    "Dress To Impress Case": (
        "dti",
        199,
        [
            ("500 DTI Cash|cash", 50),
            ("Базовая сумка|skin", 60),
            ("1 000 DTI Cash|cash", 120),
            ("Pose Pack 1 & 2|gp", 200),
            ("VIP на неделю|gp", 350),
            ("Makeup Pass|gp", 450),
            ("VIP Monthly|gp", 1500),
            ("ДЖЕКПОТ: Permanent VIP + Mo-Cap|gp", 10000),
        ],
    ),
    "Grow a Garden Case": (
        "growagarden",
        249,
        [
            ("50k Монет|cash", 60),
            ("Пак семян|perk", 70),
            ("100k Монет|cash", 150),
            ("Бронзовая лейка|skin", 180),
            ("Золотая кирка|skin", 250),
            ("Сборщик урожая|skin", 450),
            ("Промышленная печь|perk", 600),
            ("Трактор|skin", 1500),
            ("ДЖЕКПОТ: VIP + Инвентарь|gp", 15000),
        ],
    ),
    "99 Nights Case": (
        "99nights",
        249,
        [
            ("Бинт|perk", 20),
            ("Энергетик|perk", 40),
            ("Аптечка|perk", 60),
            ("Базовый нож выжившего|skin", 70),
            ("Улучшенный фонарик|skin", 200),
            ("Скин «Кемпер»|skin", 220),
            ("Кастомный топор|skin", 250),
            ("Радар маньяка|perk", 450),
            ("VIP Survivor Pass|gp", 600),
            ("Скин Маньяка «Тень»|skin", 1800),
            ("ДЖЕКПОТ: Админка|gp", 12000),
        ],
    ),
    "Rivals Case": (
        "rivals",
        299,
        [
            ("Скин Glock «Ржавчина»|skin", 30),
            ("Базовый нож|skin", 50),
            ("Брелок на оружие|skin", 70),
            ("Обычный дробовик|skin", 80),
            ("Скин M4 «Неон»|skin", 200),
            ("Эффект убийства|perk", 250),
            ("Эпический AK|skin", 300),
            ("Анимированный аватар|skin", 500),
            ("Мифическая Снайперка|skin", 800),
            ("Нож Карамбит|skin", 2500),
            ("ДЖЕКПОТ: Radiant Knife|skin", 20000),
        ],
    ),
    "MM2 Case": (
        "mm2",
        349,
        [
            ("Uncommon Knife|skin", 30),
            ("Rare Gun|skin", 50),
            ("Rare Knife|skin", 80),
            ("Legendary Pet|skin", 100),
            ("Эффект ножа «Пламя»|perk", 250),
            ("Legendary Knife|skin", 300),
            ("Legendary Gun|skin", 350),
            ("Classic Godly (Seer)|skin", 600),
            ("Godly Weapon (Fang)|skin", 900),
            ("Chroma Weapon|skin", 3000),
            ("ДЖЕКПОТ: Corrupt Set|skin", 25000),
        ],
    ),
    "Adopt Me Case": (
        "adoptme",
        399,
        [
            ("Cracked Egg|skin", 30),
            ("Pet Egg|skin", 50),
            ("Ultra-Rare Pet|skin", 120),
            ("Ride Зелье|perk", 250),
            ("Fly Зелье|perk", 350),
            ("Royal Egg|skin", 400),
            ("Legendary Vehicle|skin", 500),
            ("Legendary Pet (Turtle)|skin", 1200),
            ("Neon Legendary|skin", 4000),
            ("ДЖЕКПОТ: Mega Neon Shadow|skin", 35000),
        ],
    ),
    "Blox Fruits Case": (
        "bloxfruits",
        499,
        [
            ("Money Буст|perk", 150),
            ("Фрукт (Smoke)|skin", 100),
            ("Сброс статов|perk", 250),
            ("Фрукт (Magma)|skin", 350),
            ("Фрукт (Quake)|skin", 450),
        ],
    ),
}

# Фрибет-кейсы (медь): имя -> (бейдж, цена, кулдаун, [15 имён])
FB = {
    "Caixa Lixo": (
        "trash_fb",
        50,
        0,
        [
            "Обрывок карты",
            "Гвоздь",
            "Пробка",
            "Пуговица",
            "Ржавый ключ",
            "Медяк",
            "Болт",
            "Стеклышко",
            "Большая пуговица",
            "Медный слиток",
            "Серебряная монета",
            "Бронзовый кубок",
            "Золотой зуб",
            "Рубин",
            "МЕДНЫЙ ДЖЕКПОТ",
        ],
    ),
    "Caixa Diária": (
        "daily_fb",
        250,
        0,
        [
            "Медный мусор x5",
            "Старая монета",
            "Гайка-гигант",
            "Лом",
            "Пыльный кошелёк",
            "Мешочек меди",
            "Мелочь x100",
            "Бронзовый жетон",
            "Серебряный слиток",
            "Медный клад",
            "Золотая монета",
            "Бронзовый трофей",
            "Серебряный кубок",
            "Золотая корона",
            "МЕДАЛЬОН ДНЯ",
        ],
    ),
    "Caixa Semanal": (
        "weekly_fb",
        375,
        168,
        [
            "Мусорный пакет",
            "Ржавая монета",
            "Пробка-гигант",
            "Медный хлам",
            "Кошель меди",
            "Слиток x5",
            "Серебро x10",
            "Бронза x20",
            "Золото x50",
            "Кладовка",
            "Двойной мешок",
            "Золотая статуэтка",
            "Рубиновый кубок",
            "Алмазная монета",
            "СОКРОВИЩЕ НЕДЕЛИ",
        ],
    ),
    "Caixa Mensal": (
        "mega_fb",
        500,
        720,
        [
            "Пыль веков",
            "Древний лом",
            "Морёная пробка",
            "Мусорный титан",
            "Медный гигант",
            "Слиток x50",
            "Серебряная бухта",
            "Бронзовый идол",
            "Золотой телёнок",
            "Сундук лесника",
            "Казна гномов",
            "Корона короля",
            "Драконье яйцо",
            "Звезда удачи",
            "МЕГА-ДЖЕКПОТ МЕСЯЦА",
        ],
    ),
}


def build15(items):
    """Дотянуть список до 15 предметов паками робуксов, отсортировать по цене."""
    parsed = []
    for spec, v in items:
        name, itype = spec.rsplit("|", 1)
        parsed.append((name, itype, v))
    for rv, rr in ROBUX_PACKS:
        if len(parsed) >= 15:
            break
        if not any(abs(v - rv) < rv * 0.5 for _, _, v in parsed):
            parsed.append((f"Пак: {rv} Робуксов", "cash", rr))
    parsed.sort(key=lambda x: x[2])
    while len(parsed) < 15:
        parsed.append(parsed[-1])
    return parsed[:15]


def upsert(conn, name, price, currency, badge, rows, cooldown=0):
    row = conn.execute("SELECT id FROM cases WHERE name=%s", (name,)).fetchone()
    rtp = '{"new": 0.95, "active": 0.88, "veteran": 0.85}'
    if row is None:
        cid = conn.execute(
            "INSERT INTO cases (name, price_units, currency, cooldown_hours, rtp_profile, active) "
            "VALUES (%s,%s,%s,%s,%s,TRUE) RETURNING id",
            (name, price, currency, cooldown, rtp),
        ).fetchone()[0]
    else:
        cid = row[0]
        conn.execute(
            "UPDATE cases SET price_units=%s, currency=%s, cooldown_hours=%s, "
            "active=TRUE WHERE id=%s",
            (price, currency, cooldown, cid),
        )
    conn.execute("UPDATE case_rewards SET weight=0 WHERE case_id=%s", (cid,))
    existing = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM case_rewards WHERE case_id=%s ORDER BY id", (cid,)
        ).fetchall()
    ]
    for i, (label, _itype, value) in enumerate(rows):
        w = TIER_W[i]
        if i < len(existing):
            conn.execute(
                "UPDATE case_rewards SET reward_type='balance', game_key=%s, label=%s, "
                "nominal_units=%s, weight=%s, region=NULL WHERE id=%s",
                (badge, label, value, w, existing[i]),
            )
        else:
            conn.execute(
                "INSERT INTO case_rewards (case_id, reward_type, game_key, label, "
                "nominal_units, weight, region) VALUES (%s,'balance',%s,%s,%s,%s,NULL)",
                (cid, badge, label, value, w),
            )
    print(f"{name}: {price} {currency}, 15 предметов")


def main():
    with psycopg.connect(DSN) as conn:
        keep = list(CASES) + list(FB)
        conn.execute("UPDATE cases SET active = FALSE WHERE name <> ALL(%s)", (keep,))
        for name, (badge, price, items) in CASES.items():
            upsert(conn, name, price, "units", badge, build15(items))
        for name, (badge, price, cooldown, names) in FB.items():
            factors = (
                0.06,
                0.1,
                0.14,
                0.18,
                0.22,
                0.4,
                0.5,
                0.7,
                0.9,
                1.2,
                1.5,
                2.0,
                3.0,
                5.0,
                12.0,
            )
            rows = [
                (n, "perk", max(1, int(price * f))) for n, f in zip(names, factors, strict=False)
            ]
            upsert(conn, name, price, "freebets", badge, rows, cooldown)
        conn.commit()
    print("done")


if __name__ == "__main__":
    main()
