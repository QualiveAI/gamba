from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db import get_conn
from app.games.crash import play_crash
from app.games.mines import cashout, reveal, start
from app.games.shell import play_shell
from app.games.upgrade import do_upgrade

router = APIRouter(prefix="/games", tags=["games"])


class UpgradeRequest(BaseModel):
    item_price: int
    target_price: int
    client_seed: str = "s"


class CrashRequest(BaseModel):
    bet: int
    cashout_at: float
    client_seed: str = "s"


class MinesStartRequest(BaseModel):
    bet: int
    mine_count: int


class MinesRevealRequest(BaseModel):
    session_id: int
    cell: int


class ShellRequest(BaseModel):
    bet: int
    guess: int
    client_seed: str = "s"


@router.post("/upgrade")
async def upgrade(body: UpgradeRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await do_upgrade(conn, user, body.item_price, body.target_price, body.client_seed)


@router.post("/crash")
async def crash(body: CrashRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await play_crash(conn, user, body.bet, body.cashout_at, body.client_seed)


@router.post("/mines/start")
async def mines_start(body: MinesStartRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await start(conn, user, body.bet, body.mine_count)


@router.post("/mines/reveal")
async def mines_reveal(body: MinesRevealRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await reveal(conn, body.session_id, body.cell, user)


@router.post("/mines/cashout")
async def mines_cashout(session_id: int, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await cashout(conn, session_id, user)


@router.post("/shell")
async def shell(body: ShellRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await play_shell(conn, user, body.bet, body.guess, body.client_seed)
