"""Совместимые точки входа отключённой legacy-проверки.

Отсутствие подтверждения активации не доказывает, что карту безопасно выдать снова.
Старые задания поэтому не меняют gift_codes и не вызывают внешних поставщиков.
"""


async def schedule_verify(conn, code_id: int):
    return None


async def run_verification(conn, code_id: int):
    return {"status": "manual_review", "legacy": True, "read_only": True}
