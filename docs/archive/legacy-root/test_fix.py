[P] Testing allowed_modifiers function with plugin fallback.
import sys
sys.path.insert(0, "c:\\Артём\\Бизнес\\Ваня\\Drop\\RB\\roblox-case-platform\\backend")

from core.engine.rtp.config import allowed_modifiers
from core.registry.registry import registry

# Register MLBB adapter to test fallback
from plugins.games.mlbb.adapter import MlbbAdapter
registry.register(MlbbAdapter())

# Test mlbb modifiers
mods = allowed_modifiers("mlbb")
print(f"MLBB allowed_modifiers: {mods}")
print(f"Expected: ['f_win', 'f_bet']")
print(f"Match: {mods == ['f_win', 'f_bet']}")

# Test with another game that has no modifiers
mods_none = allowed_modifiers("nonexistent_game")
print(f"\nNonexistent game allowed_modifiers: {mods_none}")
print(f"Expected: []")
print(f"Match: {mods_none == []}")