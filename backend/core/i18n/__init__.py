import os

import yaml


def load(locale):
    path = os.path.join("locales", f"{locale}.yaml")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    # fallback
    if locale != "en":
        return load("en")
    return {}
