import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest

from app.db import close_pool, init_pool


@pytest.fixture(autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()
