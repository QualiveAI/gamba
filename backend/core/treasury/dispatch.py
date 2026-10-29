async def plan(conn, dry_run=True):
    routing = __import__("core.treasury.routing", fromlist=["load_routing"]).load_routing()
    return {"dry_run": dry_run, "routing": routing}
