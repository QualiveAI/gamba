def render(template: str, vars: dict) -> str:
    out = template
    for k, v in (vars or {}).items():
        out = out.replace("{" + k + "}", str(v))
    return out
