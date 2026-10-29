import yaml


def load_routing(path="configs/treasury.yaml"):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # validate sum
    alloc = (
        data.get("arctic", {}).get("allocation_pct", 0)
        + data.get("onesix", {}).get("allocation_pct", 0)
        + data.get("otc", {}).get("allocation_pct", 0)
        + data.get("reserve", {}).get("allocation_pct", 0)
    )
    if alloc != 100:
        raise ValueError("allocation must sum to 100")  # noqa: B904
    return data
