async def apply_actions(conn, user_id, score):
    if score.level == "high":
        await conn.execute(
            "INSERT INTO antifraud_flags (user_id, rule, score, details) VALUES (%s, %s, %s, %s)",
            (user_id, "high_risk", 100, {"reasons": score.reasons}),
        )
        await conn.commit()
        return "freeze"
    if score.level == "medium":
        await conn.execute(
            "INSERT INTO antifraud_flags (user_id, rule, score, details) VALUES (%s, %s, %s, %s)",
            (user_id, "medium_risk", 50, {"reasons": score.reasons}),
        )
        await conn.commit()
        return "hold"
    return "pass"
