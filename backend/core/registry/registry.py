import builtins
import importlib
import os
from typing import Any


class PluginRegistry:
    def __init__(self):
        self._items: dict[tuple[str, str, str | None], Any] = {}

    def register(self, obj) -> None:
        key = getattr(obj, "key", None)
        ptype = getattr(obj, "type", None)
        geo = getattr(obj, "geo", None)
        manifest = getattr(obj, "MANIFEST", None)
        if manifest:
            key = manifest.get("key", key)
            ptype = manifest.get("type", ptype)
            geo = manifest.get("geo", geo)
        self._items[(ptype, key, geo)] = obj

    def get(self, ptype: str, key: str, geo: str | None = None):
        if (ptype, key, geo) in self._items:
            return self._items[(ptype, key, geo)]
        # fallback any geo
        for (t, k, _g), obj in self._items.items():
            if t == ptype and k == key:
                return obj
        return None

    def list(self, ptype: str, geo: str | None = None):
        out = []
        for (t, _k, g), obj in self._items.items():
            if t == ptype and (geo is None or g == geo or g is None):
                out.append(obj)
        return out

    def validate_all(self, env=None) -> builtins.list[str]:
        errors = []
        seen = set()
        for (ptype, key, geo), obj in self._items.items():
            if (ptype, key, geo) in seen:
                errors.append(f"duplicate {ptype}/{key}/{geo}")
            seen.add((ptype, key, geo))
            manifest = getattr(obj, "MANIFEST", None)
            if manifest:
                enabled_env = manifest.get("enabled_env")
                if enabled_env and not os.getenv(enabled_env):
                    # disabled, skip
                    continue
            # contract conformance: check has required attrs/methods loosely
            if ptype == "game":
                for attr in ("game_key", "display_name", "prize_catalog"):
                    if not hasattr(obj, attr):
                        errors.append(f"{key} missing {attr}")
            if ptype == "payment":
                for attr in ("rail_key", "geo", "create_payment"):
                    if not hasattr(obj, attr):
                        errors.append(f"{key} missing {attr}")
            if ptype == "prize":
                for attr in ("channel_key", "deliver"):
                    if not hasattr(obj, attr):
                        errors.append(f"{key} missing {attr}")
        return errors

    def health(self) -> dict:
        out = {}
        for (ptype, key, geo), obj in self._items.items():
            hc = getattr(obj, "healthcheck", None)
            out[f"{ptype}:{key}:{geo}"] = hc() if callable(hc) else "ok"
        return out


registry = PluginRegistry()


def register(obj):
    registry.register(obj)


def discover_plugins(plugin_paths=None):
    if plugin_paths is None:
        plugin_paths = []
    for path in plugin_paths:
        try:
            mod = importlib.import_module(path)
            if hasattr(mod, "register"):
                mod.register(registry)
        except Exception:
            pass


def hot_reload(plugin_path: str):
    mod = importlib.import_module(plugin_path)
    importlib.reload(mod)
    if hasattr(mod, "register"):
        mod.register(registry)
    return True
