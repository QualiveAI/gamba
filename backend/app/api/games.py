from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db import get_conn
from app.games.crash import cash_crash, play_crash, start_crash
from app.games.mines import cashout, reveal, start
from app.games.shell import pick_shell, play_shell, start_shell
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


class CrashStartRequest(BaseModel):
    bet: int


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


class ShellStartRequest(BaseModel):
    bet: int
    level: int = 1
    client_seed: str = "s"


class ShellPickRequest(BaseModel):
    session_id: int
    guess: int


@router.post("/upgrade")
async def upgrade(body: UpgradeRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await do_upgrade(conn, user, body.item_price, body.target_price, body.client_seed)


@router.post("/crash")
async def crash(body: CrashRequest, user=Depends(get_current_user)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        return await play_crash(conn, user, body.bet, body.cashout_at, body.client_seed)


@router.post("/crash/start")
async def crash_start(body: CrashStartRequest, user=Depends(get_current_user)):  # noqa: E501, B008
    async with get_conn() as conn:
        try:
            return await start_crash(conn, user, body.bet)
        except ValueError as e:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904


@router.post("/crash/cash")
async def crash_cash(session_id: int, user=Depends(get_current_user)):  # noqa: E501, B008
    async with get_conn() as conn:
        try:
            return await cash_crash(conn, user, session_id)
        except ValueError as e:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904


@router.post("/mines/start")
async def mines_start(body: MinesStartRequest, user=Depends(get_current_user)):  # noqa: E501, B008
    async with get_conn() as conn:
        try:
            return await start(conn, user, body.bet, body.mine_count)
        except ValueError as e:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904


@router.post("/mines/reveal")
async def mines_reveal(body: MinesRevealRequest, user=Depends(get_current_user)):  # noqa: E501, B008
    async with get_conn() as conn:
        return await reveal(conn, body.session_id, body.cell, user)


@router.post("/mines/cashout")
async def mines_cashout(session_id: int, user=Depends(get_current_user)):  # noqa: E501, B008
    async with get_conn() as conn:
        return await cashout(conn, session_id, user)


@router.post("/shell")
async def shell(body: ShellRequest, user=Depends(get_current_user)):  # noqa: E501, B008
    async with get_conn() as conn:
        return await play_shell(conn, user, body.bet, body.guess, body.client_seed)


@router.post("/shell/start")
async def shell_start(body: ShellStartRequest, user=Depends(get_current_user)):  # noqa: E501, B008
    async with get_conn() as conn:
        try:
            return await start_shell(conn, user, body.bet, body.level, body.client_seed)
        except ValueError as e:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904


@router.post("/shell/pick")
async def shell_pick(body: ShellPickRequest, user=Depends(get_current_user)):  # noqa: E501, B008
    async with get_conn() as conn:
        try:
            return await pick_shell(conn, user, body.session_id, body.guess)
        except ValueError as e:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=str(e))  # noqa: B904
