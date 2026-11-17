"""AI 盯盘后台进程：每 30 分钟评估一次持仓并自动抛售。

用户在前端开启 AI 盯盘后，设置会写入数据库；本模块的守护线程会扫描所有
已开启盯盘的用户，按策略滑块调用模型给出持有 / 部分抛出 / 全部平仓结论，
并直接按最新行情自动卖出，结果写回 ai_watch_settings 供前端展示。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from . import database, trading
from .deepseek import _watch_strategy_label, watch_holdings
from .universe import lot_size, platform_of_symbol

logger = logging.getLogger(__name__)

WATCH_INTERVAL_MINUTES = 30
WATCH_INTERVAL_SECONDS = WATCH_INTERVAL_MINUTES * 60
WORKER_POLL_SECONDS = 60
MAX_WATCH_HOLDINGS = 12

_user_locks: dict[int, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def _user_lock(user_id: int) -> threading.Lock:
    with _user_locks_guard:
        lock = _user_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _user_locks[user_id] = lock
        return lock


def _clamp_strategy(value) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = 50
    return max(0, min(100, score))


def _parse_result(raw) -> dict | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _iso(value) -> str | None:
    # 数据库 DATETIME 不带时区，按服务器本地时间原样返回，前端按本地时间展示。
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, str) and value:
        return value
    return None


def get_settings(user_id: int) -> dict:
    database.ensure_schema()
    with database.cursor() as cur:
        cur.execute(
            """
            SELECT user_id, enabled, strategy, last_run_at, last_result,
                   last_error, updated_at
            FROM ai_watch_settings
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        return {
            "user_id": user_id,
            "enabled": False,
            "strategy": 50,
            "last_run_at": None,
            "last_result": None,
            "last_error": None,
            "updated_at": None,
        }
    return {
        "user_id": int(row["user_id"]),
        "enabled": bool(row.get("enabled")),
        "strategy": _clamp_strategy(row.get("strategy")),
        "last_run_at": _iso(row.get("last_run_at")),
        "last_result": _parse_result(row.get("last_result")),
        "last_error": row.get("last_error") or None,
        "updated_at": _iso(row.get("updated_at")),
    }


def save_settings(user_id: int, enabled: bool, strategy: int) -> dict:
    database.ensure_schema()
    score = _clamp_strategy(strategy)
    with database.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ai_watch_settings
                (user_id, enabled, strategy, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                enabled = VALUES(enabled),
                strategy = VALUES(strategy),
                updated_at = NOW()
            """,
            (user_id, 1 if enabled else 0, score),
        )
    return get_settings(user_id)


def status(user_id: int) -> dict:
    settings = get_settings(user_id)
    last_run = settings.get("last_run_at")
    next_run = None
    if settings.get("enabled"):
        now = datetime.now()
        base = None
        if last_run:
            try:
                base = datetime.fromisoformat(last_run)
            except ValueError:
                base = None
        if base is not None and base.tzinfo is not None:
            base = base.astimezone().replace(tzinfo=None)
        if base is None:
            # 还没跑过：守护线程会在下一次轮询（约 1 分钟内）立即评估。
            next_run = now.isoformat(timespec="seconds")
        else:
            next_run = max(
                now, base + timedelta(minutes=WATCH_INTERVAL_MINUTES)
            ).isoformat(timespec="seconds")
    return {
        **settings,
        "strategy_label": _watch_strategy_label(settings["strategy"]),
        "interval_minutes": WATCH_INTERVAL_MINUTES,
        "next_run_at": next_run,
        "worker_running": worker.running,
    }


def _aggregate_holdings(summary: dict) -> list[dict]:
    aggregated: dict[str, dict] = {}
    for item in summary.get("positions") or []:
        symbol = item.get("symbol")
        if not symbol:
            continue
        shares = int(item.get("shares") or 0)
        if shares <= 0:
            continue
        bucket = aggregated.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": item.get("name") or symbol,
                "shares": 0,
                "lot_size": int(item.get("lot_size") or lot_size(symbol)),
                "cost": 0.0,
                "market_value": 0.0,
                "profit": 0.0,
                "price": float(item.get("price") or 0),
            },
        )
        bucket["shares"] += shares
        bucket["cost"] += float(item.get("buy_price") or 0) * shares
        bucket["market_value"] += float(item.get("market_value") or 0)
        bucket["profit"] += float(item.get("profit") or 0)
        if item.get("price") is not None:
            bucket["price"] = float(item["price"])

    holdings: list[dict] = []
    for bucket in aggregated.values():
        shares = bucket["shares"]
        cost = round(bucket["cost"], 2)
        market_value = round(bucket["market_value"], 2)
        holdings.append(
            {
                "symbol": bucket["symbol"],
                "name": bucket["name"],
                "shares": shares,
                "lot_size": bucket["lot_size"],
                "buy_price": round(cost / shares, 4) if shares else 0.0,
                "price": round(bucket["price"], 4),
                "market_value": market_value,
                "profit": round(bucket["profit"], 2),
                "profit_pct": (
                    round(bucket["profit"] / cost * 100, 2) if cost else 0.0
                ),
            }
        )
    holdings.sort(key=lambda item: item["market_value"], reverse=True)
    return holdings


def _executable_shares(
    action: str, suggested: int, available: int, lot: int = 100
) -> int:
    """把模型建议换算成可成交的整手股数；0 表示不操作。"""
    if action == "全部平仓":
        return available
    if action != "部分抛出":
        return 0
    step = max(1, int(lot or 100))
    lots = max(0, int(suggested) // step) * step
    if lots < step and available >= step:
        lots = step
    if lots >= available:
        return available
    return lots


async def _auto_sell(
    user_id: int, positions: list[dict], holdings: list[dict]
) -> tuple[list[dict], list[str]]:
    holding_map = {item["symbol"]: item for item in holdings}
    executed: list[dict] = []
    warnings: list[str] = []
    for item in positions:
        symbol = item.get("symbol")
        holding = holding_map.get(symbol)
        if not holding:
            continue
        action = item.get("action") or "持有"
        available = int(holding.get("shares") or 0)
        suggested = int(item.get("sell_shares") or 0)
        lot = int(holding.get("lot_size") or lot_size(symbol))
        shares = _executable_shares(action, suggested, available, lot)
        if shares <= 0:
            continue
        try:
            if shares >= available:
                sale = await asyncio.to_thread(
                    trading.close_position, user_id, symbol
                )
                detail = sale.get("closed") or {}
            else:
                sale = await asyncio.to_thread(
                    trading.sell_position, user_id, symbol, shares
                )
                detail = sale.get("sold") or {}
        except Exception as exc:
            logger.warning(
                "auto sell failed for user %s %s: %s", user_id, symbol, exc
            )
            warnings.append(f"{symbol} 自动卖出失败：{exc}")
            continue
        executed.append(
            {
                "symbol": symbol,
                "name": item.get("name") or holding.get("name") or symbol,
                "action": "全部平仓" if shares >= available else "部分抛出",
                "shares": int(detail.get("shares") or shares),
                "price": detail.get("price"),
                "proceeds": detail.get("proceeds"),
                "realized": detail.get("realized"),
                "realized_pct": detail.get("realized_pct"),
            }
        )
        logger.info(
            "ai watch auto sold user=%s %s %s shares", user_id, symbol, shares
        )
    return executed, warnings


def _record_run(
    user_id: int, result: dict | None = None, error: str | None = None
) -> None:
    try:
        with database.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_watch_settings
                SET last_run_at = NOW(), last_result = %s, last_error = %s,
                    updated_at = NOW()
                WHERE user_id = %s
                """,
                (
                    json.dumps(result, ensure_ascii=False) if result else None,
                    (error or "")[:500] or None,
                    user_id,
                ),
            )
    except Exception:
        logger.warning("failed to persist ai watch result", exc_info=True)


def _empty_result(strategy: int, summary_text: str) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": _clamp_strategy(strategy),
        "strategy_label": _watch_strategy_label(strategy),
        "summary": summary_text,
        "positions": [],
        "executed": [],
        "warnings": [],
        "meta": {},
    }


async def evaluate_user(
    user_id: int,
    strategy: int,
    *,
    refresh: bool = True,
    execute: bool = True,
) -> dict:
    """评估一个用户的持仓，必要时自动抛售，并持久化结果。"""
    lock = _user_lock(user_id)
    if not lock.acquire(blocking=False):
        # 同一用户正在评估中，直接返回上一次结果，避免重复下单。
        latest = await asyncio.to_thread(get_settings, user_id)
        previous = latest.get("last_result") or _empty_result(
            strategy, "盯盘正在执行中，请稍候。"
        )
        return {**previous, "busy": True}
    try:
        return await _evaluate_locked(
            user_id, strategy, refresh=refresh, execute=execute
        )
    finally:
        lock.release()


async def _evaluate_locked(
    user_id: int, strategy: int, *, refresh: bool, execute: bool
) -> dict:
    score = _clamp_strategy(strategy)
    try:
        summary = await asyncio.to_thread(trading.account_summary, user_id)
    except Exception as exc:
        logger.warning("ai watch account failed for %s: %s", user_id, exc)
        error = "持仓数据读取失败，请稍后重试"
        await asyncio.to_thread(_record_run, user_id, None, error)
        raise RuntimeError(error) from exc

    holdings = _aggregate_holdings(summary)
    warnings = list(summary.get("warnings") or [])
    if len(holdings) > MAX_WATCH_HOLDINGS:
        warnings.append("持仓股票较多，本次只分析市值最高的 12 只。")

    if not holdings:
        result = _empty_result(score, "当前没有持仓，无需盯盘。")
        result["warnings"] = warnings
        await asyncio.to_thread(_record_run, user_id, result)
        return result

    capped = holdings[:MAX_WATCH_HOLDINGS]
    symbols = [item["symbol"] for item in capped]
    markets = {platform_of_symbol(symbol) for symbol in symbols}
    market = markets.pop() if len(markets) == 1 else "MIXED"
    # 延迟导入，避免 main <-> ai_watch 循环依赖。
    from .main import _build_portfolio

    try:
        portfolio = await asyncio.to_thread(_build_portfolio, symbols, refresh)
    except Exception as exc:
        logger.warning("ai watch portfolio failed for %s: %s", user_id, exc)
        error = "持仓行情暂不可用，请稍后重试"
        await asyncio.to_thread(_record_run, user_id, None, error)
        raise RuntimeError(error) from exc

    try:
        result = await watch_holdings(portfolio, capped, score, market)
    except Exception as exc:
        logger.warning("ai watch model failed for %s: %s", user_id, exc)
        error = "智能盯盘暂时不可用，请稍后重试"
        await asyncio.to_thread(_record_run, user_id, None, error)
        raise RuntimeError(error) from exc

    executed: list[dict] = []
    if execute:
        # 评估期间用户可能已关闭盯盘，下单前再确认一次开关状态。
        try:
            latest = await asyncio.to_thread(get_settings, user_id)
            still_enabled = bool(latest.get("enabled"))
        except Exception:
            still_enabled = False
        if still_enabled:
            executed, sell_warnings = await _auto_sell(
                user_id, result.get("positions") or [], capped
            )
            warnings.extend(sell_warnings)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **result,
        "executed": executed,
        "warnings": list(dict.fromkeys(warnings)),
        "auto_execute": bool(execute),
        "interval_minutes": WATCH_INTERVAL_MINUTES,
    }
    await asyncio.to_thread(_record_run, user_id, payload)
    return payload


def _due_users() -> list[dict]:
    try:
        with database.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, strategy
                FROM ai_watch_settings
                WHERE enabled = 1
                  AND (last_run_at IS NULL
                       OR last_run_at <= DATE_SUB(NOW(), INTERVAL %s SECOND))
                """,
                (WATCH_INTERVAL_SECONDS,),
            )
            return cur.fetchall()
    except Exception:
        logger.warning("failed to scan ai watch users", exc_info=True)
        return []


def run_due_users() -> None:
    for row in _due_users():
        if worker.stopping:
            return
        user_id = int(row.get("user_id") or 0)
        if user_id <= 0:
            continue
        try:
            asyncio.run(
                evaluate_user(
                    user_id,
                    _clamp_strategy(row.get("strategy")),
                    refresh=True,
                    execute=True,
                )
            )
        except Exception as exc:
            logger.warning("ai watch cycle failed for %s: %s", user_id, exc)


class AiWatchWorker:
    """后台守护线程：每分钟检查一次到期用户，每 30 分钟评估并自动抛售。"""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ai-watch-monitor", daemon=True
        )
        self._thread.start()
        logger.info(
            "AI watch worker started, evaluating every %s minutes",
            WATCH_INTERVAL_MINUTES,
        )

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # 留出启动时间，避免和建表/首次请求抢数据库。
        if self._stop.wait(10):
            return
        while not self._stop.is_set():
            try:
                database.ensure_schema()
                run_due_users()
            except Exception:
                logger.exception("ai watch worker cycle failed")
            if self._stop.wait(WORKER_POLL_SECONDS):
                return


worker = AiWatchWorker()
