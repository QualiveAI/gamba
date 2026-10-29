import secrets

from app.economy.rng import ProvablyFairRNG
from app.economy.rtp import resolve_rtp
from app.economy.segments import compute_segment
from core.engine.ledger.ledger import post_entry


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
            "SELECT id, name, price_units, rtp_profile, active FROM cases WHERE id = %s", (case_id,)
        )
    ).fetchone()
    if case is None or not case["active"]:
        raise ValueError("case not found")  # noqa: B904
    rewards = await (
        await conn.execute(
            "SELECT id, reward_type, game_key, nominal_units, weight, region FROM case_rewards WHERE case_id = %s",  # noqa: E501
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

    await post_entry(conn, user["id"], "units", -price, "case_open", f"case:{case_id}")

    credit = int(reward["nominal_units"])
    if not zero_idx and scale_credit != 1.0:
        credit = int(round(credit * scale_credit))
    await post_entry(conn, user["id"], "units", credit, "case_win", f"reward:{reward['id']}")

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
