import importlib


def hot_reload(plugin_path: str):
    mod = importlib.import_module(plugin_path)
    importlib.reload(mod)
    if hasattr(mod, "register"):
        from core.registry.registry import registry

        mod.register(registry)
    return True
