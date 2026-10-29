import importlib
import os


def discover_plugins(plugin_paths=None):
    if plugin_paths is None:
        plugin_paths = []
    for path in plugin_paths:
        try:
            mod = importlib.import_module(path)
            if hasattr(mod, "register"):
                mod.register(__import__("core.registry.registry", fromlist=["registry"]).registry)
        except Exception:
            pass
    # filesystem plugins
    base = os.path.join(os.getcwd(), "plugins")
    if os.path.isdir(base):
        for root, _dirs, files in os.walk(base):
            if "plugin.py" in files:
                rel = os.path.relpath(root, os.getcwd()).replace(os.sep, ".")
                try:
                    mod = importlib.import_module(rel + ".plugin")
                    if hasattr(mod, "register"):
                        from core.registry.registry import registry

                        mod.register(registry)
                except Exception:
                    pass
