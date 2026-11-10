"""Сид каталога из WINDROP-Game-Demo: 14 кейсов × 15 предметов, PT-BR.

Значения предметов, шансы и картинки — 1:1 из демо (tools/demo_catalog.json).
RTP кейса = фактический EV демо (rtp_profile.standard), чтобы open_case
ничего не перекашивал. Имена кейсов/предметов переведены на PT-BR.
FK-безопасный upsert: существующие case_rewards обновляются по позиции.

Запуск: python tools/seed_demo.py  (без -I: user site-packages)
"""

import json
import os
import re
from pathlib import Path

import psycopg
import psycopg.rows

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

CATALOG = Path(__file__).resolve().parent / "demo_catalog.json"

# ---------- PT-BR ----------
CASE_NAMES = {
    "brainrot": "Brainrot",
    "brookhaven": "Brookhaven",
    "dti": "Dress To Impress",
    "garden": "Grow a Garden",
    "nights": "99 Noites (Survival)",
    "rivals": "Rivals",
    "mm2": "Murder Mystery 2",
    "adopt": "Adopt Me!",
    "blox": "Blox Fruits",
    "pets": "Pet Simulator 99",
    "trash": "Caixa Lixo",
    "daily": "Caixa Diária",
    "weekly": "Caixa Semanal",
    "monthly": "Caixa Mensal",
}

# Полные переводы уникальных RU-названий (fallback — пословная замена ниже)
ITEM_NAMES = {
    "Fly Зелье": "Poção Fly",
    "Ride Зелье": "Poção Ride",
    "Huge Pet (Обычный)": "Huge Pet (Comum)",
    "Money Буст": "Booster de Dinheiro",
    "VIP на неделю": "VIP por 1 semana",
    "Анимированный аватар": "Avatar animado",
    "Анимированный титул «Босс Качалки»": "Título animado «Rei da Malhação»",
    "Аптечка": "Kit médico",
    "Аура «Кринж» (токсичные испарения)": "Aura «Cringe» (vapores tóxicos)",
    "Аура «Пиксельная пыль»": "Aura «Poeira de Pixel»",
    "Базовая сумка": "Bolsa básica",
    "Базовый нож": "Faca básica",
    "Базовый нож выжившего": "Faca básica de sobrevivência",
    "Базовый пет «Кот-батон»": "Pet «Gato-Pão»",
    "Базовый самокат": "Patinete básico",
    "Базовый энергетик": "Energético básico",
    "Банка «Grimace Shake» (Расходник)": "«Grimace Shake» (consumível)",
    "Бинт": "Bandagem",
    "Брелок на оружие": "Pingente de arma",
    "Бриллианты (10M)": "Diamantes (10M)",
    "Бронзовая лейка": "Regador de bronze",
    "Бустер «Сигма-Фокус»": "Booster «Foco Sigma»",
    "ДЖЕКПОТ (5 000 Робуксов + статус «Абсолютный Сигма» + Пет Босс-Мозг)": "JACKPOT (5.000 Robux + título «Sigma Absoluto» + Pet Boss Cérebro)",
    "ДЖЕКПОТ (Corrupt Set)": "JACKPOT (Corrupt Set)",
    "ДЖЕКПОТ (Mega Neon Shadow)": "JACKPOT (Mega Neon Shadow)",
    "ДЖЕКПОТ (Permanent Dragon)": "JACKPOT (Permanent Dragon)",
    "ДЖЕКПОТ (Permanent VIP + Mo-Cap)": "JACKPOT (Permanent VIP + Mo-Cap)",
    "ДЖЕКПОТ (Radiant Knife)": "JACKPOT (Radiant Knife)",
    "ДЖЕКПОТ (Titanic Pet)": "JACKPOT (Titanic Pet)",
    "ДЖЕКПОТ (VIP + 10k)": "JACKPOT (VIP + 10k)",
    "ДЖЕКПОТ (VIP + Инвентарь)": "JACKPOT (VIP + Inventário)",
    "ДЖЕКПОТ (Админка)": "JACKPOT (Admin)",
    "ДЖЕКПОТ: 1 000 Робуксов + Титул «Ноулайфер»": "JACKPOT: 1.000 Robux + título «No-Lifer»",
    "ДЖЕКПОТ: 100 Робуксов + Титул «Король Помойки»": "JACKPOT: 100 Robux + título «Rei do Lixo»",
    "ДЖЕКПОТ: 5 000 Робуксов + Пет «Гигачад»": "JACKPOT: 5.000 Robux + Pet «Gigachad»",
    "ДЖЕКПОТ: 500 Робуксов": "JACKPOT: 500 Robux",
    "Зелье удачи": "Poção da sorte",
    "Золотая кирка": "Picareta dourada",
    "Золотой мусорный бак (Шляпа)": "Lixeira dourada (chapéu)",
    "Камень-пет «Просто камень»": "Pet pedra «Só Uma Pedra»",
    "Картонка «Will work for Robux» (Аксессуар)": "Placa «Will work for Robux» (acessório)",
    "Кастомный топор": "Machado custom",
    "Кепка «Нубик»": "Boné «Noob»",
    "Легендарная Аура «Brainrot»": "Aura lendária «Brainrot»",
    "Легендарный маунт «Bing Chilling Dragon»": "Montaria lendária «Bing Chilling Dragon»",
    "Маунт «Унитаз на колесах»": "Montaria «Vaso com Rodas»",
    "Мифическая Снайперка": "Sniper mítica",
    "Нож Карамбит": "Faca Karambit",
    "Обычный дробовик": "Shotgun comum",
    "Пак семян": "Pacote de sementes",
    "Пасс на бассейн": "Passe da piscina",
    "Пасс на дома": "Passe das casas",
    "Пасс на лица": "Passe de rostos",
    "Пасс на премиум авто": "Passe de carro premium",
    "Пет «Большой Шлёпа» (Флоппа)": "Pet «Big Floppa»",
    "Пет «Грустный Хомяк»": "Pet «Hamster Triste»",
    "Пет «Капибара»": "Pet «Capivara»",
    "Пиксельные очки «Thug Life»": "Óculos pixel «Thug Life»",
    "Питомец «Гигачад Доге»": "Pet «Gigachad Doge»",
    "Питомец «Крутящийся Кот Максвелл»": "Pet «Gato Maxwell Girando»",
    "Питомец «Шайлушай» (Смурф-кот)": "Pet «Shailushai» (gato smurf)",
    "Платный Hoverboard": "Hoverboard pago",
    "Промышленная печь": "Forno industrial",
    "Пустой стаканчик из-под кофе (Аксессуар)": "Copo de café vazio (acessório)",
    "Радар маньяка": "Radar do maníaco",
    "Рваный башмак (Скин)": "Sapato rasgado (skin)",
    "Роликовые коньки": "Patins",
    "Рюкзак «Амогус»": "Mochila «Amogus»",
    "Сборщик урожая": "Coletor de colheita",
    "Сброс статов": "Reset de stats",
    "Скин Glock «Ржавчина»": "Skin Glock «Ferrugem»",
    "Скин M4 «Неон»": "Skin M4 «Neon»",
    "Скин «Базовый Сигма»": "Skin «Sigma Básico»",
    "Скин «Кемпер»": "Skin «Camper»",
    "Скин «Пакет на голову»": "Skin «Saco na Cabeça»",
    "Скин Маньяка «Тень»": "Skin do maníaco «Sombra»",
    "Скин на инструмент «Вантуз Скибиди»": "Skin de ferramenta «Desentupidor Skibidi»",
    "Титул «L + Ratio»": "Título «L + Ratio»",
    "Титул над головой «Из Огайо»": "Título «De Ohio»",
    "Трактор": "Trator",
    "Улучшенный фонарик": "Lanterna melhorada",
    "Физ. Фрукт (Smoke)": "Fruta física (Smoke)",
    "Футболка «Я пережил понедельник»": "Camiseta «Sobrevivi à Segunda»",
    "Ховерборд": "Hoverboard",
    "Эмоция «Мьюинг»": "Emote «Mewing»",
    "Эмоция «Плач»": "Emote «Choro»",
    "Эмоция «Танец Скибиди»": "Emote «Dança Skibidi»",
    "Энергетик": "Energético",
    "Эпическая Аура «Brainrot»": "Aura épica «Brainrot»",
    "Эпический AK": "AK épico",
    "Эффект ножа «Пламя»": "Efeito de faca «Chama»",
    "Эффект убийства": "Efeito de eliminação",
}

# Пословные замены для числовых робуксов
WORD_RE = re.compile(r"(Робуксов|Робукса|Робукс\b)")
NUM_RE = re.compile(r"(\d) (?=\d)")


def translate(name: str) -> str:
    if name in ITEM_NAMES:
        return ITEM_NAMES[name]
    out = WORD_RE.sub("Robux", name)
    out = NUM_RE.sub(r"\1.", out)  # 1 000 -> 1.000
    return out


def avg(v) -> int:
    return int(round(sum(v) / 2 if isinstance(v, list) else v))


def main() -> None:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    with psycopg.connect(DSN, row_factory=psycopg.rows.dict_row) as conn:
        keep = [CASE_NAMES[c["id"]] for c in data["cases"]]
        conn.execute("UPDATE cases SET active = FALSE WHERE name <> ALL(%s)", (keep,))
        for c in data["cases"]:
            name = CASE_NAMES[c["id"]]
            price = int(c["price"])
            currency = "units" if c["currency"] == "gold" else "freebets"
            items = c["items"]
            weights = [float(i["chance"]) for i in items]
            values = [avg(i["value"]) for i in items]
            W = sum(weights)
            ev = sum(w * v for w, v in zip(weights, values, strict=False)) / W
            rtp = round(ev / price, 4)
            # Кулдауны фрибет-кейсов — защита экономики меди
            cooldown = {"weekly": 168, "monthly": 720}.get(c["id"], 0)

            row = conn.execute(
                "SELECT id FROM cases WHERE name = %s", (name,)
            ).fetchone()
            if row:
                cid = row["id"]
                conn.execute(
                    "UPDATE cases SET price_units=%s, currency=%s, cooldown_hours=%s, "
                    "rtp_profile=%s, active=TRUE, cover=%s WHERE id=%s",
                    (price, currency, cooldown, json.dumps({"standard": rtp}), c["cover"], cid),
                )
            else:
                cid = conn.execute(
                    "INSERT INTO cases (name, price_units, currency, cooldown_hours, rtp_profile, active, cover) "
                    "VALUES (%s,%s,%s,%s,%s,TRUE,%s) RETURNING id",
                    (name, price, currency, cooldown, json.dumps({"standard": rtp}), c["cover"]),
                ).fetchone()["id"]

            # FK-безопасно: обновляем существующие награды по позиции, недостающие вставляем
            existing = conn.execute(
                "SELECT id FROM case_rewards WHERE case_id=%s ORDER BY id", (cid,)
            ).fetchall()
            conn.execute("UPDATE case_rewards SET weight=0 WHERE case_id=%s", (cid,))
            for i, item in enumerate(items):
                label = translate(item["name"])
                tier = item["tier"]
                weight = float(item["chance"])
                image = item.get("image")
                if i < len(existing):
                    rid = existing[i]["id"]
                    conn.execute(
                        "UPDATE case_rewards SET reward_type='balance', game_key=%s, label=%s, "
                        "nominal_units=%s, weight=%s, image=%s, rarity=%s, region=NULL WHERE id=%s",
                        (c["id"], label, values[i], weight, image, tier, rid),
                    )
                else:
                    conn.execute(
                        "INSERT INTO case_rewards (case_id, reward_type, game_key, label, "
                        "nominal_units, weight, image, rarity, region) "
                        "VALUES (%s,'balance',%s,%s,%s,%s,%s,%s,NULL)",
                        (cid, c["id"], label, values[i], weight, image, tier),
                    )
            print(f"{name}: {price} {currency}, {len(items)} предметов, RTP={rtp:.3f}")
        conn.commit()
    print("OK")


if __name__ == "__main__":
    main()
