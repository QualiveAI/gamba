import os

import yaml

from core.registry.registry import registry


def load_game_config(game_key: str) -> dict:
    path = f"configs/games/{game_key}.yaml"
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def allowed_modifiers(game_key: str) -> list[str]:
    # 1. Try YAML config first
    cfg = load_game_config(game_key)
    modifiers = cfg.get("allowed_modifiers") or cfg.get("rtp_modifiers", {}).get("allowed")
    if modifiers:
        return modifiers
    # 2. Fall back to plugin registry's game adapter attribute
    plugin = registry.get("game", game_key)
    if plugin is not None and hasattr(plugin, "allowed_modifiers"):
        return list(plugin.allowed_modifiers)
    # 3. Last resort: empty list
    return []
