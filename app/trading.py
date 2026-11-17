from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
from fastapi import HTTPException

from . import database, providers
from .config import MAX_SELECTION
from .universe import (
    display_name,
    is_valid_symbol,
    lot_size,
    lookup,
    normalize_symbol,
)

logger = logging.getLogger(__name__)


def _money(value) -> float:
    return round(float(value or 0), 2)


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def _month_start(today: date) -> date:
    return today.replace(day=1)


def _month_base_price(
    symbol: str,
    history_cache: dict[str, pd.DataFrame | None],
    month_start: date,
) -> float | None:
    frame = history_cache.get(symbol)
    if frame is None or frame.empty:
        return None
    try:
        earlier = frame[frame.index < pd.Timestamp(month_start)]
        if earlier.empty:
            return None
        return float(earlier["Close"].iloc[-1])
    except Exception:
        return None


def _load_position_rows(user_id: int) -> tuple[dict | None, list[dict]]:
    with database.cursor() as cur:
        cur.execute(
            "SELECT id, username, balance, is_simulated FROM users WHERE id = %s",
            (user_id,),
        )
        user = cur.fetchone()
        if not user:
            return None, []
        cur.execute(
            """
            SELECT p.id, p.trade_id, p.symbol, p.name, p.shares, p.buy_price,
                   p.cost, p.last_price, p.created_at, t.cost AS trade_cost
            FROM trade_positions p
            JOIN trades t ON t.id = p.trade_id
            WHERE p.user_id = %s AND t.status = 'open'
            ORDER BY p.id
            """,
            (user_id,),
        )
        positions = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) AS n, MAX(created_at) AS last_at FROM trades WHERE user_id = %s AND status = 'open'",
            (user_id,),
        )
        trade_meta = cur.fetchone() or {"n": 0, "last_at": None}
    return {**user, "trade_meta": trade_meta}, positions


def _realized_totals(user_id: int, today: date, month_start: date) -> dict:
    try:
        with database.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(profit), 0) AS total_profit,
                       COALESCE(SUM(CASE WHEN trade_date = %s THEN today_profit ELSE 0 END), 0) AS today_profit,
                       COALESCE(SUM(CASE WHEN trade_date >= %s THEN month_profit ELSE 0 END), 0) AS month_profit
                FROM trade_realized
                WHERE user_id = %s
                """,
                (today, month_start, user_id),
            )
            row = cur.fetchone() or {}
    except Exception:
        logger.warning("failed to load realized profit", exc_info=True)
        row = {}
    return {
        "total": _money(row.get("total_profit")),
        "today": _money(row.get("today_profit")),
        "month": _money(row.get("month_profit")),
    }


def account_summary(user_id: int) -> dict:
    """Compute account metrics from live market data and persist them."""
    database.ensure_schema()
    user, positions = _load_position_rows(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    balance = _money(user.get("balance"))
    is_simulated = bool(user.get("is_simulated"))
    created_at = datetime.now(timezone.utc).isoformat()
    today = date.today()
    month_start = _month_start(today)
    realized = _realized_totals(user_id, today, month_start)
    if not positions:
        return {
            "balance": balance,
            "position_value": 0.0,
            "holding_cost": 0.0,
            "realtime_profit": 0.0,
            "total_assets": balance,
            "today_profit": realized["today"],
            "month_profit": realized["month"],
            "total_profit": realized["total"],
            "position_count": 0,
            "trade_count": 0,
            "last_trade_at": None,
            "is_simulated": is_simulated,
            "updated_at": created_at,
            "warnings": [],
            "positions": [],
        }

    symbols = list(dict.fromkeys(row["symbol"] for row in positions))
    quote_result = providers.get_quotes(symbols)
    quote_map = {
        quote["symbol"]: quote
        for quote in quote_result.get("quotes", [])
        if quote.get("symbol")
    }
    warnings = [
        f"{item.get('symbol')} 的行情暂不可用，已使用最近一次记录的价格"
        for item in quote_result.get("errors", [])
    ]

    history_needed = []
    for row in positions:
        created = _as_date(row.get("created_at"))
        if created is None or created < month_start:
            symbol = row["symbol"]
            if symbol not in history_needed:
                history_needed.append(symbol)

    history_cache: dict[str, pd.DataFrame | None] = {}
    if history_needed:
        with ThreadPoolExecutor(max_workers=min(4, len(history_needed))) as executor:
            futures = {
                executor.submit(providers.get_history_frame, symbol): symbol
                for symbol in history_needed
            }
            for future, symbol in futures.items():
                try:
                    history_cache[symbol] = future.result()
                except Exception as exc:
                    logger.info("month history unavailable for %s: %s", symbol, exc)
                    history_cache[symbol] = None

    today_profit = 0.0
    month_profit = 0.0
    total_profit = 0.0
    position_value = 0.0
    holding_cost = 0.0
    detail: list[dict] = []
    trade_totals: dict[int, dict] = {}

    for row in positions:
        symbol = row["symbol"]
        shares = int(row["shares"] or 0)
        buy_price = float(row["buy_price"] or 0)
        cost = float(row["cost"] or 0)
        quote = quote_map.get(symbol)
        last_price = float(row["last_price"] or 0)

        if quote and quote.get("price") is not None:
            price = float(quote["price"])
        else:
            price = last_price or buy_price

        value = round(price * shares, 2)
        row_profit = round(value - cost, 2)
        position_value += value
        holding_cost += cost
        total_profit += row_profit

        created = _as_date(row.get("created_at"))
        if created is not None and created >= today:
            today_base = buy_price
        elif quote and quote.get("previous_close"):
            today_base = float(quote["previous_close"])
        else:
            # 行情缺失时无法判断日内涨跌，按持平处理，避免把累计收益误算成今日收益。
            today_base = price
        today_profit += round((price - today_base) * shares, 2)

        if created is not None and created >= month_start:
            month_base = buy_price
        else:
            month_base = _month_base_price(symbol, history_cache, month_start)
            if month_base is None:
                month_base = buy_price
        month_profit += round((price - month_base) * shares, 2)

        detail.append(
            {
                "symbol": symbol,
                "name": row.get("name") or display_name(symbol),
                "shares": shares,
                "lot_size": lot_size(symbol),
                "buy_price": round(buy_price, 4),
                "price": round(price, 4),
                "market_value": value,
                "profit": row_profit,
            }
        )

        bucket = trade_totals.setdefault(
            int(row["trade_id"]),
            {
                "cost": 0.0,
                "value": 0.0,
                "profit": 0.0,
                "trade_cost": float(row.get("trade_cost") or 0),
            },
        )
        bucket["cost"] += cost
        bucket["value"] += value
        bucket["profit"] += row_profit

    position_value = round(position_value, 2)
    holding_cost = round(holding_cost, 2)
    realtime_profit = round(position_value - holding_cost, 2)
    today_profit = round(today_profit + realized["today"], 2)
    month_profit = round(month_profit + realized["month"], 2)
    total_profit = round(total_profit + realized["total"], 2)

    try:
        with database.cursor() as cur:
            for item, row in zip(detail, positions):
                cur.execute(
                    """
                    UPDATE trade_positions
                    SET last_price = %s, market_value = %s, profit = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        item["price"],
                        item["market_value"],
                        item["profit"],
                        row["id"],
                    ),
                )
            realized_by_trade: dict[int, float] = {}
            cur.execute(
                """
                SELECT trade_id, COALESCE(SUM(profit), 0) AS realized
                FROM trade_realized
                WHERE user_id = %s
                GROUP BY trade_id
                """,
                (user_id,),
            )
            for item in cur.fetchall():
                realized_by_trade[int(item["trade_id"])] = float(
                    item.get("realized") or 0
                )
            for trade_id, totals in trade_totals.items():
                realized_trade = realized_by_trade.get(trade_id, 0.0)
                profit = round(totals["profit"] + realized_trade, 2)
                base_cost = totals["trade_cost"] or totals["cost"]
                pct = round(profit / base_cost * 100, 4) if base_cost else 0.0
                cur.execute(
                    """
                    UPDATE trades
                    SET market_value = %s, profit = %s, profit_pct = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        round(totals["value"], 2),
                        profit,
                        pct,
                        trade_id,
                    ),
                )
    except Exception:
        logger.warning("failed to persist account summary", exc_info=True)

    return {
        "balance": balance,
        "position_value": position_value,
        "holding_cost": holding_cost,
        "realtime_profit": realtime_profit,
        "total_assets": round(balance + position_value, 2),
        "today_profit": today_profit,
        "month_profit": month_profit,
        "total_profit": total_profit,
        "position_count": len(detail),
        "trade_count": int((user.get("trade_meta") or {}).get("n") or 0),
        "last_trade_at": (user.get("trade_meta") or {}).get("last_at"),
        "is_simulated": is_simulated,
        "updated_at": created_at,
        "warnings": warnings,
        "positions": detail,
    }


def execute_auto_trade(
    user_id: int,
    allocations: list[dict],
    capital: float | None = None,
) -> dict:
    """Record a screened allocation as a trade and deduct it from the balance."""
    database.ensure_schema()
    if not allocations:
        raise HTTPException(status_code=422, detail="没有可交易的配置")
    if len(allocations) > MAX_SELECTION:
        raise HTTPException(
            status_code=422, detail=f"单次最多交易 {MAX_SELECTION} 只股票"
        )

    cleaned: list[dict] = []
    seen: set[str] = set()
    for raw in allocations:
        symbol = normalize_symbol(str(raw.get("symbol") or ""))
        if not symbol or not is_valid_symbol(symbol):
            raise HTTPException(status_code=422, detail=f"无效代码: {raw.get('symbol')}")
        if symbol in seen:
            raise HTTPException(status_code=422, detail=f"配置中存在重复代码: {symbol}")
        seen.add(symbol)
        try:
            shares = int(raw.get("shares"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{symbol} 的股数无效")
        if shares <= 0:
            raise HTTPException(status_code=422, detail=f"{symbol} 的股数需大于 0")
        lot = lot_size(symbol)
        if shares % lot != 0:
            note = "港股每手股数因股票而异" if symbol.endswith(".HK") else "整手交易"
            raise HTTPException(
                status_code=422,
                detail=f"{symbol} 的股数需为 {lot} 的整数倍（{note}）",
            )
        cleaned.append({"symbol": symbol, "shares": shares})

    quote_result = providers.get_quotes([item["symbol"] for item in cleaned])
    quote_map = {
        quote["symbol"]: quote
        for quote in quote_result.get("quotes", [])
        if quote.get("symbol") and quote.get("price") is not None
    }
    missing = [item["symbol"] for item in cleaned if item["symbol"] not in quote_map]
    if missing:
        raise HTTPException(
            status_code=502,
            detail=f"无法获取 {'、'.join(missing)} 的实时价格，请稍后再试",
        )

    items: list[dict] = []
    total_cost = 0.0
    for item in cleaned:
        quote = quote_map[item["symbol"]]
        price = float(quote["price"])
        cost = round(price * item["shares"], 2)
        lookup_item = lookup(item["symbol"])
        name = (
            quote.get("name")
            or (lookup_item["name"] if lookup_item else "")
            or display_name(item["symbol"])
        )
        items.append(
            {
                "symbol": item["symbol"],
                "name": name,
                "shares": item["shares"],
                "price": round(price, 4),
                "cost": cost,
            }
        )
        total_cost += cost
    total_cost = round(total_cost, 2)

    requested_capital = round(float(capital), 2) if capital else total_cost
    connection = database.connect()
    try:
        connection.begin()
        with connection.cursor() as cur:
            cur.execute(
                "SELECT balance, is_simulated FROM users WHERE id = %s FOR UPDATE",
                (user_id,),
            )
            user = cur.fetchone()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")
            balance = float(user.get("balance") or 0)
            if total_cost > balance + 0.001:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"账户余额不足：当前余额 ¥{balance:,.2f}，"
                        f"本次交易需要 ¥{total_cost:,.2f}，请联系客服充值"
                    ),
                )
            is_simulated = bool(user.get("is_simulated"))
            mode = "simulated" if is_simulated else "live"

            cur.execute(
                "UPDATE users SET balance = balance - %s WHERE id = %s",
                (Decimal(str(total_cost)), user_id),
            )
            cur.execute(
                """
                INSERT INTO trades
                    (user_id, mode, capital, cost, market_value, profit,
                     profit_pct, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 0, 0, 'open', NOW(), NOW())
                """,
                (
                    user_id,
                    mode,
                    Decimal(str(requested_capital)),
                    Decimal(str(total_cost)),
                    Decimal(str(total_cost)),
                ),
            )
            trade_id = cur.lastrowid
            for item in items:
                cur.execute(
                    """
                    INSERT INTO trade_positions
                        (trade_id, user_id, symbol, name, shares, buy_price,
                         cost, last_price, market_value, profit, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, NOW(), NOW())
                    """,
                    (
                        trade_id,
                        user_id,
                        item["symbol"],
                        item["name"][:64],
                        item["shares"],
                        Decimal(str(item["price"])),
                        Decimal(str(item["cost"])),
                        Decimal(str(item["price"])),
                        Decimal(str(item["cost"])),
                    ),
                )
        connection.commit()
    except HTTPException:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        logger.exception("auto trade failed")
        raise HTTPException(status_code=503, detail="交易记录失败，请稍后重试") from exc
    finally:
        connection.close()

    summary = account_summary(user_id)
    return {
        "ok": True,
        "trade": {
            "id": trade_id,
            "mode": mode,
            "capital": requested_capital,
            "cost": total_cost,
            "positions": items,
            "status": "open",
        },
        "summary": summary,
    }


def _sell_position(
    user_id: int, raw_symbol: str, raw_shares: int | None = None
) -> dict:
    """Sell all or part of one symbol's open shares at the latest quote."""
    database.ensure_schema()
    symbol = normalize_symbol(str(raw_symbol or ""))
    if not symbol or not is_valid_symbol(symbol):
        raise HTTPException(status_code=422, detail=f"无效代码: {raw_symbol}")

    quote_result = providers.get_quotes([symbol])
    quote = next(
        (
            item
            for item in quote_result.get("quotes", [])
            if item.get("symbol") == symbol and item.get("price") is not None
        ),
        None,
    )
    if quote is None:
        raise HTTPException(
            status_code=502,
            detail=f"无法获取 {symbol} 的实时价格，请稍后再试",
        )
    price = float(quote["price"])
    name = quote.get("name") or display_name(symbol)
    today = date.today()
    month_start = _month_start(today)

    history_cache: dict[str, pd.DataFrame | None] = {}
    try:
        with database.cursor() as cur:
            cur.execute(
                """
                SELECT MIN(p.created_at) AS first_at
                FROM trade_positions p
                JOIN trades t ON t.id = p.trade_id
                WHERE p.user_id = %s AND p.symbol = %s AND t.status = 'open'
                """,
                (user_id, symbol),
            )
            first_at = _as_date((cur.fetchone() or {}).get("first_at"))
        if first_at is not None and first_at < month_start:
            try:
                history_cache[symbol] = providers.get_history_frame(symbol)
            except Exception as exc:
                logger.info("month history unavailable for %s: %s", symbol, exc)
                history_cache[symbol] = None
    except Exception:
        logger.info("failed to inspect position history for %s", symbol, exc_info=True)

    connection = database.connect()
    try:
        connection.begin()
        with connection.cursor() as cur:
            cur.execute(
                "SELECT balance, is_simulated FROM users WHERE id = %s FOR UPDATE",
                (user_id,),
            )
            user = cur.fetchone()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

            cur.execute(
                """
                SELECT p.id, p.trade_id, p.shares, p.buy_price, p.cost, p.created_at
                FROM trade_positions p
                JOIN trades t ON t.id = p.trade_id
                WHERE p.user_id = %s AND p.symbol = %s AND t.status = 'open'
                FOR UPDATE
                """,
                (user_id, symbol),
            )
            rows = cur.fetchall()
            if not rows:
                raise HTTPException(
                    status_code=404, detail=f"当前没有 {symbol} 的持仓"
                )

            available_shares = sum(int(row["shares"] or 0) for row in rows)
            if raw_shares is None:
                total_shares = available_shares
            else:
                try:
                    total_shares = int(raw_shares)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail="卖出股数无效")
                if total_shares <= 0:
                    raise HTTPException(status_code=422, detail="卖出股数需大于 0")
                lot = lot_size(symbol)
                if total_shares % lot != 0 and total_shares != available_shares:
                    note = "港股每手股数因股票而异" if symbol.endswith(".HK") else "一手为 100 股"
                    raise HTTPException(
                        status_code=422,
                        detail=f"卖出股数需为 {lot} 的整数倍（{note}）",
                    )
                if total_shares > available_shares:
                    raise HTTPException(
                        status_code=422,
                        detail=f"最多可卖出 {available_shares} 股",
                    )
            full = total_shares == available_shares

            previous_close = float(quote.get("previous_close") or 0)
            today_realized = 0.0
            month_realized = 0.0
            total_cost = 0.0
            remaining_to_sell = total_shares
            realized_rows: list[dict] = []
            delete_ids: list[int] = []
            per_trade: dict[int, dict] = {}
            for row in rows:
                if remaining_to_sell <= 0:
                    break
                shares = int(row["shares"] or 0)
                if shares <= 0:
                    continue
                take = min(shares, remaining_to_sell)
                cost_total = float(row["cost"] or 0)
                cost = round(cost_total * take / shares, 2)
                if take >= shares:
                    cost = cost_total
                buy_price = float(row["buy_price"] or 0)
                created = _as_date(row.get("created_at"))
                if created is not None and created >= today:
                    today_base = buy_price
                elif previous_close > 0:
                    today_base = previous_close
                else:
                    today_base = price
                if created is not None and created >= month_start:
                    month_base = buy_price
                else:
                    month_base = _month_base_price(
                        symbol, history_cache, month_start
                    )
                    if month_base is None:
                        month_base = buy_price
                row_today = round((price - today_base) * take, 2)
                row_month = round((price - month_base) * take, 2)
                today_realized += row_today
                month_realized += row_month
                total_cost += cost
                trade_id = int(row["trade_id"])
                realized_rows.append(
                    {
                        "trade_id": trade_id,
                        "shares": take,
                        "buy_price": buy_price,
                        "cost": cost,
                        "proceeds": round(price * take, 2),
                        "profit": round(price * take - cost, 2),
                        "today_profit": row_today,
                        "month_profit": row_month,
                    }
                )
                bucket = per_trade.setdefault(
                    trade_id, {"shares": 0, "cost": 0.0}
                )
                bucket["shares"] += take
                bucket["cost"] += cost
                if take >= shares:
                    delete_ids.append(int(row["id"]))
                else:
                    new_shares = shares - take
                    new_cost = round(cost_total - cost, 2)
                    new_value = round(price * new_shares, 2)
                    new_profit = round(new_value - new_cost, 2)
                    cur.execute(
                        """
                        UPDATE trade_positions
                        SET shares = %s, cost = %s, last_price = %s,
                            market_value = %s, profit = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (
                            new_shares,
                            Decimal(str(new_cost)),
                            Decimal(str(price)),
                            Decimal(str(new_value)),
                            Decimal(str(new_profit)),
                            int(row["id"]),
                        ),
                    )
                remaining_to_sell -= take

            if remaining_to_sell > 0:
                raise HTTPException(status_code=422, detail="可卖出股数不足")
            total_cost = round(total_cost, 2)
            proceeds = round(price * total_shares, 2)
            realized = round(proceeds - total_cost, 2)
            realized_pct = round(realized / total_cost * 100, 4) if total_cost else 0.0

            for item in realized_rows:
                cur.execute(
                    """
                    INSERT INTO trade_realized
                        (user_id, trade_id, symbol, name, shares, buy_price,
                         sale_price, cost, proceeds, profit, today_profit,
                         month_profit, trade_date, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        user_id,
                        item["trade_id"],
                        symbol,
                        str(name)[:64],
                        item["shares"],
                        Decimal(str(item["buy_price"])),
                        Decimal(str(price)),
                        Decimal(str(item["cost"])),
                        Decimal(str(item["proceeds"])),
                        Decimal(str(item["profit"])),
                        Decimal(str(item["today_profit"])),
                        Decimal(str(item["month_profit"])),
                        today,
                    ),
                )

            cur.execute(
                "UPDATE users SET balance = balance + %s WHERE id = %s",
                (Decimal(str(proceeds)), user_id),
            )

            if delete_ids:
                placeholders = ",".join(["%s"] * len(delete_ids))
                cur.execute(
                    f"DELETE FROM trade_positions WHERE id IN ({placeholders})",
                    delete_ids,
                )

            for trade_id in per_trade:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM trade_positions WHERE trade_id = %s",
                    (trade_id,),
                )
                remaining = int((cur.fetchone() or {}).get("n") or 0)
                cur.execute(
                    "SELECT COALESCE(SUM(profit), 0) AS realized, "
                    "COALESCE((SELECT cost FROM trades WHERE id = %s), 0) AS trade_cost "
                    "FROM trade_realized WHERE trade_id = %s",
                    (trade_id, trade_id),
                )
                realized_trade = cur.fetchone() or {}
                trade_profit = round(
                    float(realized_trade.get("realized") or 0), 2
                )
                trade_cost = float(realized_trade.get("trade_cost") or 0)
                if remaining:
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(COALESCE(last_price, buy_price) * shares), 0) AS value,
                               COALESCE(SUM(cost), 0) AS cost
                        FROM trade_positions
                        WHERE trade_id = %s
                        """,
                        (trade_id,),
                    )
                    totals = cur.fetchone() or {}
                    value = round(float(totals.get("value") or 0), 2)
                    cost = round(float(totals.get("cost") or 0), 2)
                    profit = round(value - cost + trade_profit, 2)
                    profit_pct = (
                        round(profit / trade_cost * 100, 4)
                        if trade_cost
                        else 0.0
                    )
                    cur.execute(
                        """
                        UPDATE trades
                        SET market_value = %s, profit = %s, profit_pct = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (value, profit, profit_pct, trade_id),
                    )
                else:
                    profit_pct = (
                        round(trade_profit / trade_cost * 100, 4)
                        if trade_cost
                        else 0.0
                    )
                    cur.execute(
                        """
                        UPDATE trades
                        SET market_value = 0, profit = %s, profit_pct = %s,
                            status = 'closed', updated_at = NOW()
                        WHERE id = %s
                        """,
                        (trade_profit, profit_pct, trade_id),
                    )
        connection.commit()
    except HTTPException:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        logger.exception("close position failed")
        raise HTTPException(status_code=503, detail="平仓失败，请稍后重试") from exc
    finally:
        connection.close()

    summary = account_summary(user_id)
    return {
        "ok": True,
        "sold": {
            "symbol": symbol,
            "name": name,
            "shares": total_shares,
            "remaining_shares": available_shares - total_shares,
            "full": full,
            "price": round(price, 4),
            "proceeds": proceeds,
            "cost": total_cost,
            "realized": realized,
            "realized_pct": realized_pct,
            "today_realized": round(today_realized, 2),
            "month_realized": round(month_realized, 2),
        },
        "summary": summary,
    }


def close_position(user_id: int, raw_symbol: str) -> dict:
    """Sell every open share of one symbol at the latest quote."""
    result = _sell_position(user_id, raw_symbol, None)
    result["closed"] = result.pop("sold")
    return result


def sell_position(user_id: int, raw_symbol: str, shares: int) -> dict:
    """Sell part of one symbol's open shares at the latest quote."""
    return _sell_position(user_id, raw_symbol, shares)
