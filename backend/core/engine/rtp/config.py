import os

import yaml


def load_game_config(game_key: str) -> dict:
    path = f"configs/games/{game_key}.yaml"
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def allowed_modifiers(game_key: str) -> list[str]:
    cfg = load_game_config(game_key)
    return cfg.get("allowed_modifiers", []) or cfg.get("rtp_modifiers", {}).get("allowed", [])
