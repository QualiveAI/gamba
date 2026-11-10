# Fix Report: allowed_modifiers() Plugin Registry Fallback

## Problem
The MLBB game adapter has `allowed_modifiers = ["f_win", "f_bet"]` as a class attribute, but the `allowed_modifiers()` function in `core/engine/rtp/config.py` only read from YAML config (`configs/games/mlbb.yaml`), which had no `allowed_modifiers` key. This caused the MLBB RTP modifiers to never be applied.

## Solution
Modified `core/engine/rtp/config.py` to add a fallback chain:
1. Try YAML config first (original behavior)
2. If no modifiers in YAML, fall back to plugin registry's game adapter `allowed_modifiers` attribute
3. Last resort: return empty list

## Code Change
```python
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
```

## Verification
- Syntax validated via AST parse
- All 12 game tests pass (mlbb, pubgm, standoff2)
- Full non-database test suite: 22/22 tests pass
- The 4 config/currency tests fail only due to missing PostgreSQL connection (infrastructure, not code)