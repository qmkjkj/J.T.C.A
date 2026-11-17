from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, database, trading

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account", tags=["account"])


class TradeItem(BaseModel):
    symbol: str = Field(default="", max_length=16)
    shares: int = Field(gt=0, le=10_000_000)


class AutoTradeRequest(BaseModel):
    capital: float | None = Field(default=None, gt=0, le=1_000_000_000)
    allocations: list[TradeItem] = Field(default_factory=list)


class ClosePositionRequest(BaseModel):
    symbol: str = Field(default="", max_length=16)


class SellPositionRequest(BaseModel):
    symbol: str = Field(default="", max_length=16)
    shares: int = Field(gt=0, le=10_000_000)


@router.get("/summary")
def account_summary(user: dict = Depends(auth.require_user)) -> dict:
    try:
        return trading.account_summary(int(user["user_id"]))
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        logger.warning("account summary database error: %s", exc)
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("account summary failed")
        raise HTTPException(status_code=500, detail="账户数据读取失败") from exc


@router.post("/trade")
def auto_trade(
    body: AutoTradeRequest,
    user: dict = Depends(auth.require_user),
) -> dict:
    allocations = [
        {"symbol": item.symbol, "shares": item.shares} for item in body.allocations
    ]
    try:
        return trading.execute_auto_trade(
            int(user["user_id"]), allocations, body.capital
        )
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        logger.warning("auto trade database error: %s", exc)
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("auto trade failed")
        raise HTTPException(status_code=500, detail="自动交易失败") from exc


@router.post("/close-position")
def close_position(
    body: ClosePositionRequest,
    user: dict = Depends(auth.require_user),
) -> dict:
    try:
        return trading.close_position(int(user["user_id"]), body.symbol)
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        logger.warning("close position database error: %s", exc)
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("close position failed")
        raise HTTPException(status_code=500, detail="平仓失败") from exc


@router.post("/sell-position")
def sell_position(
    body: SellPositionRequest,
    user: dict = Depends(auth.require_user),
) -> dict:
    try:
        return trading.sell_position(int(user["user_id"]), body.symbol, body.shares)
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        logger.warning("sell position database error: %s", exc)
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("sell position failed")
        raise HTTPException(status_code=500, detail="部分卖出失败") from exc
