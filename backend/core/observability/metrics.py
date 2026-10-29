_counters = {}
_histograms = {}


def inc(name, labels=None):
    key = (name, tuple(sorted((labels or {}).items())))
    _counters[key] = _counters.get(key, 0) + 1


def observe(name, value, labels=None):
    key = (name, tuple(sorted((labels or {}).items())))
    _histograms.setdefault(key, []).append(value)


def render_prometheus():
    lines = []
    for (name, labels), val in _counters.items():
        label_str = ",".join(f'{k}="{v}"' for k, v in labels)
        lines.append(f"{name}{{{label_str}}} {val}")
    return "\n".join(lines) + "\n"
