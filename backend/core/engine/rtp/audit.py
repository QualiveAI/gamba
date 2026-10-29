async def log_decision(
    conn, user_id, game_key, rtp_effective, modifiers, reason, config_version_id=None
):
    await conn.execute(
        "INSERT INTO events (user_id, event_type, payload) VALUES (%s, %s, %s)",
        (
            user_id,
            "rtp_decision",
            {
                "game_key": game_key,
                "rtp_effective": rtp_effective,
                "modifiers": modifiers,
                "reason": reason,
                "config_version_id": config_version_id,
            },
        ),
    )
    await conn.commit()


async def log_config_change(conn, who, value, reason):
    await conn.execute(
        "INSERT INTO events (user_id, event_type, payload) VALUES (%s, %s, %s)",
        (None, "rtp_config_change", {"who": who, "value": value, "reason": reason}),
    )
    await conn.commit()
