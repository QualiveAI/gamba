import secrets
import uuid
from datetime import UTC, datetime, timedelta

from app.economy.rng import ProvablyFairRNG
from app.economy.rtp import resolve_rtp
from app.economy.segments import compute_segment
from core.engine.ledger.ledger import post_entry


def _rarity(credit: int, price: int) -> str:
    """Редкость по отношению цены предмета к цене кейса."""
    ratio = credit / max(1, price)
    for name, lo in (("Legendary", 5), ("Epic", 2), ("Rare", 1), ("Uncommon", 0.5)):
        if ratio >= lo:
            return name
    return "Common"


async def _pick_reward(rewards, roll, adjusted_weights):
    total = sum(adjusted_weights)
    target = roll * total
    acc = 0.0
    for r, w in zip(rewards, adjusted_weights, strict=False):
        acc += w
        if target <= acc:
            return r
    return rewards[-1]


async def open_case(conn, user, case_id, client_seed):
    case = await (
        await conn.execute(
            "SELECT id, name, price_units, rtp_profile, active, currency, cooldown_hours "
            "FROM cases WHERE id = %s",
            (case_id,),
        )
    ).fetchone()
    if case is None or not case["active"]:
        raise ValueError("case not found")  # noqa: B904
    rewards = await (
        await conn.execute(
            "SELECT id, reward_type, game_key, label, nominal_units, weight, region, image, rarity FROM case_rewards WHERE case_id = %s",  # noqa: E501
            (case_id,),
        )
    ).fetchall()
    if not rewards:
        raise ValueError("no rewards")  # noqa: B904

    rtp = await resolve_rtp(conn, user, case)
    price = int(case["price_units"])

    # adjust weights
    weights = [float(r["weight"]) for r in rewards]
    nominals = [int(r["nominal_units"]) for r in rewards]
    W = sum(weights)
    if W <= 0:
        raise ValueError("invalid weights")  # noqa: B904
    E0 = sum(w * v for w, v in zip(weights, nominals, strict=False)) / W
    target_E = rtp * price

    # identify zero rewards
    zero_idx = [i for i, v in enumerate(nominals) if v == 0]
    nz_idx = [i for i, v in enumerate(nominals) if v != 0]
    adjusted = list(weights)
    if zero_idx and nz_idx:
        Wnz = sum(weights[i] for i in nz_idx)
        if Wnz > 0:
            Enz = sum(weights[i] * nominals[i] for i in nz_idx) / Wnz
            if Enz > 0 and target_E < Enz:
                # need p_zero
                p_zero = 1.0 - (target_E / Enz)
                if p_zero < 0:
                    p_zero = 0.0
                if p_zero > 0.99:
                    p_zero = 0.99
                # weight for zeros collectively
                if p_zero > 0:
                    wz = (p_zero / (1.0 - p_zero)) * Wnz
                    # distribute among zero rewards by original weight (or equal)
                    orig_zero_w = sum(weights[i] for i in zero_idx)
                    if orig_zero_w <= 0:
                        orig_zero_w = len(zero_idx)
                    for i in zero_idx:
                        base = weights[i] if weights[i] > 0 else 1.0
                        adjusted[i] = wz * (base / orig_zero_w)
                # non-zero unchanged
    # if no zero rewards, scale credited amount later
    scale_credit = 1.0
    if not zero_idx and E0 > 0:
        scale_credit = target_E / E0

    server_seed = secrets.token_hex(32)
    row = await (
        await conn.execute(
            "SELECT COUNT(*) AS c FROM case_openings WHERE user_id = %s", (user["id"],)
        )
    ).fetchone()
    nonce = int(row["c"]) + 1
    rng = ProvablyFairRNG(server_seed, client_seed, nonce)
    roll = rng.roll()
    reward = await _pick_reward(rewards, roll, adjusted)

    # Дорогие фрибет-кейсы: нужен streak отметок (>=3000 меди — 7 дней, >=12000 — 30)
    need_streak = None
    if (case["currency"] or "units") == "freebets":
        need_streak = 30 if price >= 12000 else 7 if price >= 3000 else None
    if need_streak:
        marks = await (
            await conn.execute(
                "SELECT claimed_at::date AS d FROM daily_rewards WHERE user_id = %s "
                "ORDER BY claimed_at::date DESC LIMIT 400",
                (user["id"],),
            )
        ).fetchall()
        dayset = {r["d"] for r in marks}
        today = datetime.now(UTC).date()
        cursor = today if today in dayset else today - timedelta(days=1)
        streak = 0
        while cursor in dayset:
            streak += 1
            cursor -= timedelta(days=1)
        if streak < need_streak:
            raise ValueError(f"check-in streak: precisa de {need_streak} dias seguidos")

    cooldown = int(case.get("cooldown_hours") or 0)
    if cooldown > 0:
        last = await (
            await conn.execute(
                "SELECT MAX(o.created_at) AS t FROM case_openings o "
                "JOIN cases c ON c.id = o.case_id WHERE o.user_id = %s AND c.id = %s",
                (user["id"], case_id),
            )
        ).fetchone()
        if last and last["t"]:
            elapsed = (datetime.now(UTC) - last["t"]).total_seconds() / 3600.0
            if elapsed < cooldown:
                hours_left = int(cooldown - elapsed) + 1
                raise ValueError(f"cooldown: ещё {hours_left} ч")

    case_currency = case["currency"] or "units"
    open_ref = f"case:{case_id}:{uuid.uuid4().hex[:12]}"
    await post_entry(conn, user["id"], case_currency, -price, "case_open", open_ref)

    credit = int(reward["nominal_units"])
    if not zero_idx and scale_credit != 1.0:
        credit = int(round(credit * scale_credit))
    # Предмет уходит в инвентарь (продать/апгрейднуть/вывести может сам игрок)
    await conn.execute(
        "INSERT INTO user_items (user_id, label, game_key, currency, value_coins, rarity, image) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            user["id"], reward["label"], reward["game_key"], case_currency,
            credit, reward["rarity"] or _rarity(credit, price), reward["image"],
        ),
    )
    if credit >= 100:
        from app.rewards.winfeed import record_win

        await record_win(conn, user["id"], credit, f"case:{case['name']}")

    server_seed_hash = ProvablyFairRNG.server_seed_hash(server_seed)
    cur = await conn.execute(
        "INSERT INTO case_openings (user_id, case_id, reward_id, server_seed, server_seed_hash, client_seed, nonce, roll, rtp_used) "  # noqa: E501
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, created_at",
        (
            user["id"],
            case_id,
            reward["id"],
            server_seed,
            server_seed_hash,
            client_seed,
            nonce,
            roll,
            rtp,
        ),
    )
    opening = await cur.fetchone()

    # update segment
    new_segment = await compute_segment(conn, user["id"])
    await conn.execute("UPDATE users SET segment = %s WHERE id = %s", (new_segment, user["id"]))

    await conn.commit()
    return {
        "id": opening["id"],
        "user_id": user["id"],
        "case_id": case_id,
        "reward_id": reward["id"],
        "reward_type": reward["reward_type"],
        "game_key": reward["game_key"],
        "nominal_units": int(reward["nominal_units"]),
        "item": reward["label"],
        "image": reward["image"],
        "rarity": reward["rarity"] or _rarity(credit, price),
        "chance_pct": round(float(reward["weight"]) / W * 100, 3) if W else 0,
        "credit_units": credit,
        "server_seed": server_seed,
        "server_seed_hash": server_seed_hash,
        "client_seed": client_seed,
        "nonce": nonce,
        "roll": roll,
        "rtp_used": rtp,
        "segment": new_segment,
        "created_at": opening["created_at"],
    }
