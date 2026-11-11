"""Nomes públicos PT-BR do catálogo WINDROP.

Os game keys e os nomes persistidos servem como chaves internas. Este módulo
mantém a apresentação localizada sem alterar IDs, preços, pesos ou assets.
"""

from __future__ import annotations

import re

CASE_NAMES_PT_BR = {
    "brainrot": "Brainrot",
    "brookhaven": "Brookhaven",
    "dti": "Dress to Impress",
    "garden": "Grow a Garden",
    "nights": "99 Noites: Sobrevivência",
    "rivals": "Rivals",
    "mm2": "Murder Mystery 2",
    "adopt": "Adopt Me!",
    "blox": "Blox Fruits",
    "pets": "Pet Simulator 99",
    "trash": "Caixa do Lixo",
    "daily": "Caixa Diária",
    "weekly": "Caixa Semanal",
    "monthly": "Caixa Mensal",
}

CASE_NAME_ALIASES = {
    key.lower(): value
    for key, value in {
        **CASE_NAMES_PT_BR,
        "DTI (Dress To Impress)": "Dress to Impress",
        "Growgarden": "Grow a Garden",
        "99 Noites (Survive / Хоррор)": "99 Noites: Sobrevivência",
        "99 Noites (Survive / Horror)": "99 Noites: Sobrevivência",
        "MM2 (Murder Mystery 2)": "Murder Mystery 2",
        "Мусорный кейс": "Caixa do Lixo",
        "Ежедневный кейс": "Caixa Diária",
        "Недельный кейс": "Caixa Semanal",
        "Месячный кейс": "Caixa Mensal",
    }.items()
}

# Labels antigos podem chegar do seed legado. Todos os fallbacks abaixo são
# PT-BR e não deixam texto cirílico chegar ao DOM.
ITEM_NAMES_PT_BR = {
    "50k Монет": "50 mil moedas",
    "100k Монет": "100 mil moedas",
    "Fly Зелье": "Poção Fly",
    "Ride Зелье": "Poção Ride",
    "Huge Pet (Обычный)": "Pet enorme (Comum)",
    "Money Буст": "Bônus de dinheiro",
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
    "Зелье удачи": "Poção da sorte",
    "Золотая кирка": "Picareta dourada",
    "Золотой мусорный бак (Шляпа)": "Lixeira dourada (chapéu)",
    "Камень-пет «Просто камень»": "Pet pedra «Só Uma Pedra»",
    "Картонка «Will work for Robux» (Аксессуар)": "Placa «Will work for Robux» (acessório)",
    "Кастомный топор": "Machado customizado",
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
    "Сброс статов": "Reset de atributos",
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
    "Фрукт (Magma)": "Fruta (Magma)",
    "Фрукт (Quake)": "Fruta (Quake)",
    "Фрукт (Buddha)": "Fruta (Buddha)",
    "Фрукт (Kitsune)": "Fruta (Kitsune)",
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
    "500 DTI Cash": "500 moedas DTI",
    "1 000 DTI Cash": "1.000 moedas DTI",
    "Pose Pack 1 & 2": "Pacote de poses 1 e 2",
    "Makeup Pass": "Passe de maquiagem",
    "VIP Monthly": "VIP mensal",
    "VIP Survivor Pass": "Passe VIP de sobrevivente",
    "Uncommon Knife": "Faca incomum",
    "Rare Gun": "Arma rara",
    "Rare Knife": "Faca rara",
    "Legendary Pet": "Pet lendário",
    "Legendary Knife": "Faca lendária",
    "Legendary Gun": "Arma lendária",
    "Classic Godly (Seer)": "Godly clássico (Seer)",
    "Godly Weapon (Fang)": "Arma Godly (Fang)",
    "Chroma Weapon": "Arma Chroma",
    "Cracked Egg": "Ovo rachado",
    "Pet Egg": "Ovo de pet",
    "Ultra-Rare Pet": "Pet ultrarraro",
    "Royal Egg": "Ovo real",
    "Legendary Vehicle": "Veículo lendário",
    "Legendary Pet (Turtle)": "Pet lendário (Tartaruga)",
    "Neon Legendary": "Lendário Neon",
    "2x Mastery": "Maestria 2x",
    "25M Diamonds": "25 milhões de diamantes",
    "Exclusive Egg": "Ovo exclusivo",
    "Golden/Rainbow Huge Pet": "Pet enorme dourado/arco-íris",
    "JACKPOT": "PRÊMIO MÁXIMO",
    "ДЖЕКПОТ (5 000 Робуксов + статус «Абсолютный Сигма» + Пет Босс-Мозг)": (
        "PRÊMIO MÁXIMO (5.000 Robux + título «Sigma Absoluto» + Pet Boss Cérebro)"
    ),
    "ДЖЕКПОТ (VIP + 10k)": "PRÊMIO MÁXIMO (VIP + 10 mil)",
    "ДЖЕКПОТ (Permanent VIP + Mo-Cap)": "PRÊMIO MÁXIMO (VIP permanente + Mo-Cap)",
    "ДЖЕКПОТ (VIP + Инвентарь)": "PRÊMIO MÁXIMO (VIP + inventário)",
    "ДЖЕКПОТ (Админка)": "PRÊMIO MÁXIMO (Admin)",
    "ДЖЕКПОТ (Radiant Knife)": "PRÊMIO MÁXIMO (Radiant Knife)",
    "ДЖЕКПОТ (Corrupt Set)": "PRÊMIO MÁXIMO (Corrupt Set)",
    "ДЖЕКПОТ (Mega Neon Shadow)": "PRÊMIO MÁXIMO (Mega Neon Shadow)",
    "ДЖЕКПОТ (Permanent Dragon)": "PRÊMIO MÁXIMO (Dragão permanente)",
    "ДЖЕКПОТ (Titanic Pet)": "PRÊMIO MÁXIMO (Pet Titanic)",
    "ДЖЕКПОТ: 100 Робуксов + Титул «Король Помойки»": (
        "PRÊMIO MÁXIMO: 100 Robux + título «Rei do Lixo»"
    ),
    "ДЖЕКПОТ: 500 Робуксов": "PRÊMIO MÁXIMO: 500 Robux",
    "ДЖЕКПОТ: 1 000 Робуксов + Титул «Ноулайфер»": "PRÊMIO MÁXIMO: 1.000 Robux + título «No-Lifer»",
    "ДЖЕКПОТ: 5 000 Робуксов + Пет «Гигачад»": "PRÊMIO MÁXIMO: 5.000 Robux + Pet «Gigachad»",
}

# Демо использует несколько одинаковых номиналов с разными пробелами/формами.
_ROBUX_RE = re.compile(r"^(?P<num>[0-9][0-9 .]*) Робукс(?:ов|а)?$")


def case_name(game_key: str | None, fallback: str = "Case") -> str:
    key = str(game_key or "")
    cover_key = ""
    if "cover-" in key:
        cover_key = key.rsplit("cover-", 1)[-1].split(".", 1)[0]
    return CASE_NAMES_PT_BR.get(
        key,
        CASE_NAME_ALIASES.get(
            key.lower(), CASE_NAMES_PT_BR.get(cover_key, CASE_NAME_ALIASES.get(cover_key, fallback))
        ),
    )


def item_name(name: str) -> str:
    if name in ITEM_NAMES_PT_BR:
        return ITEM_NAMES_PT_BR[name]
    match = _ROBUX_RE.match(name)
    if match:
        return f"{match.group('num').replace(' ', '.')} Robux"
    # Labels already supplied by the catalog are allowed only when they have
    # no Cyrillic; otherwise a safe generic PT-BR label prevents raw leakage.
    if re.search(r"[\u0400-\u04ff]", name):
        return "Recompensa do catálogo"
    return name
