from __future__ import annotations

import json
import logging

import pymysql
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from . import auth, database
from .config import ADMIN_COOKIE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminCredentials(BaseModel):
    username: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=128)


class CreateUserRequest(BaseModel):
    username: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=128)
    vip_level: int = Field(default=0, ge=0, le=3)
    is_simulated: int = Field(default=1, ge=0, le=1)


class StatusRequest(BaseModel):
    status: int = Field(ge=0, le=1)


class VipRequest(BaseModel):
    vip_level: int = Field(ge=0, le=3)


class BalanceRequest(BaseModel):
    balance: float = Field(ge=0, le=1_000_000_000_000)


class SimulatedRequest(BaseModel):
    is_simulated: int = Field(ge=0, le=1)


def _db_error(exc: Exception) -> HTTPException:
    logger.warning("admin database error: %s", exc)
    return HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试")


def _json_load(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


@router.post("/login")
def admin_login(request: Request, response: Response, body: AdminCredentials) -> dict:
    username = (body.username or "").strip()
    password = body.password or ""
    rate_key = auth.login_rate_key(request, "admin:" + username)
    auth.check_login_rate(rate_key)

    if not auth.verify_admin_credentials(username, password):
        auth.record_login_failure(rate_key)
        auth.log_login(request, username, False, None, "后台账号或密码错误")
        raise HTTPException(status_code=401, detail="后台账号或密码错误")

    auth.clear_login_failures(rate_key)
    try:
        database.ensure_schema()
        token = auth.create_session(
            None, True, auth.client_ip(request), auth.client_agent(request)
        )
    except Exception as exc:
        raise _db_error(exc) from exc

    auth.set_admin_cookie(response, token)
    auth.log_login(request, username, True, None, "后台登录成功")
    return {"ok": True, "admin": {"username": username, "is_admin": True}}


@router.post("/logout")
def admin_logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(ADMIN_COOKIE)
    try:
        auth.delete_session(token)
    except Exception:
        logger.warning("failed to delete admin session", exc_info=True)
    auth.clear_admin_cookie(response)
    return {"ok": True}


@router.get("/me")
def admin_me(admin: dict = Depends(auth.require_admin)) -> dict:
    return {"ok": True, "admin": admin}


@router.get("/overview")
def admin_overview(admin: dict = Depends(auth.require_admin)) -> dict:
    try:
        with database.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM users")
            total_users = int(cur.fetchone()["n"])
            cur.execute("SELECT COUNT(*) AS n FROM users WHERE status = 1")
            active_users = int(cur.fetchone()["n"])
            cur.execute(
                "SELECT COUNT(*) AS n FROM sessions WHERE expires_at > NOW() AND is_admin = 0"
            )
            active_sessions = int(cur.fetchone()["n"])
            cur.execute("SELECT COUNT(*) AS n FROM login_logs WHERE success = 1")
            total_logins = int(cur.fetchone()["n"])
            cur.execute("SELECT COUNT(*) AS n FROM login_logs WHERE success = 0")
            failed_logins = int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT COUNT(*) AS n, COALESCE(SUM(capital), 0) AS capital
                FROM screen_runs
                """
            )
            screens = cur.fetchone()
            cur.execute(
                """
                SELECT COUNT(*) AS n, COALESCE(SUM(cost), 0) AS cost,
                       COALESCE(SUM(profit), 0) AS profit
                FROM trades
                """
            )
            trades = cur.fetchone()
            cur.execute(
                """
                SELECT l.username, l.ip, l.success, l.message, l.created_at
                FROM login_logs l
                ORDER BY l.created_at DESC, l.id DESC
                LIMIT 8
                """
            )
            recent = cur.fetchall()
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("overview failed")
        raise _db_error(exc) from exc

    return {
        "users": {"total": total_users, "active": active_users},
        "sessions": {"active": active_sessions},
        "logins": {"success": total_logins, "failed": failed_logins},
        "screens": {
            "runs": int(screens["n"]),
            "capital": float(screens["capital"] or 0),
        },
        "trades": {
            "count": int(trades["n"]),
            "cost": float(trades["cost"] or 0),
            "profit": float(trades["profit"] or 0),
        },
        "recent_logins": recent,
    }


@router.get("/users")
def admin_users(
    q: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: dict = Depends(auth.require_admin),
) -> dict:
    keyword = q.strip()
    where = ""
    params: list = []
    if keyword:
        where = "WHERE u.username LIKE %s"
        params.append(f"%{keyword}%")
    try:
        with database.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM users u {where}", params)
            total = int(cur.fetchone()["n"])
            cur.execute(
                f"""
                SELECT u.id, u.username, u.status, u.vip_level, u.balance, u.is_simulated,
                       u.created_at, u.last_login_at,
                       (SELECT COUNT(*) FROM sessions s
                        WHERE s.user_id = u.id AND s.expires_at > NOW()) AS active_sessions
                FROM users u
                {where}
                ORDER BY u.id DESC
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            rows = cur.fetchall()
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("user list failed")
        raise _db_error(exc) from exc

    for row in rows:
        row["vip_level"] = int(row.get("vip_level") or 0)
        row["vip_name"] = auth.vip_name(row["vip_level"])
        row["balance"] = round(float(row.get("balance") or 0), 2)
        row["is_simulated"] = int(row.get("is_simulated") or 0)
    return {"total": total, "page": page, "page_size": page_size, "items": rows}


@router.post("/users")
def admin_create_user(
    body: CreateUserRequest,
    admin: dict = Depends(auth.require_admin),
) -> dict:
    username = auth.validate_username(body.username)
    password = auth.validate_password(body.password)
    try:
        with database.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="该用户名已存在")
            cur.execute(
                """
                INSERT INTO users
                    (username, password_hash, status, vip_level, balance, is_simulated, created_at)
                VALUES (%s, %s, 1, %s, 0, %s, NOW())
                """,
                (
                    username,
                    auth.hash_password(password),
                    body.vip_level,
                    body.is_simulated,
                ),
            )
            user_id = cur.lastrowid
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except pymysql.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="该用户名已存在") from exc
    except Exception as exc:
        logger.exception("admin create user failed")
        raise _db_error(exc) from exc
    return {
        "ok": True,
        "id": user_id,
        "username": username,
        "vip_level": body.vip_level,
        "vip_name": auth.vip_name(body.vip_level),
        "balance": 0.0,
        "is_simulated": body.is_simulated,
    }


@router.post("/users/{user_id}/status")
def admin_set_status(
    user_id: int,
    body: StatusRequest,
    admin: dict = Depends(auth.require_admin),
) -> dict:
    try:
        with database.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="用户不存在")
            cur.execute(
                "UPDATE users SET status = %s WHERE id = %s", (body.status, user_id)
            )
            if body.status == 0:
                cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("admin status update failed")
        raise _db_error(exc) from exc
    return {"ok": True, "id": user_id, "status": body.status}


@router.post("/users/{user_id}/vip")
def admin_set_vip(
    user_id: int,
    body: VipRequest,
    admin: dict = Depends(auth.require_admin),
) -> dict:
    try:
        with database.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="用户不存在")
            cur.execute(
                "UPDATE users SET vip_level = %s WHERE id = %s",
                (body.vip_level, user_id),
            )
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("admin vip update failed")
        raise _db_error(exc) from exc
    return {
        "ok": True,
        "id": user_id,
        "vip_level": body.vip_level,
        "vip_name": auth.vip_name(body.vip_level),
    }


@router.post("/users/{user_id}/balance")
def admin_set_balance(
    user_id: int,
    body: BalanceRequest,
    admin: dict = Depends(auth.require_admin),
) -> dict:
    balance = round(float(body.balance), 2)
    try:
        with database.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="用户不存在")
            cur.execute(
                "UPDATE users SET balance = %s WHERE id = %s", (balance, user_id)
            )
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("admin balance update failed")
        raise _db_error(exc) from exc
    return {"ok": True, "id": user_id, "balance": balance}


@router.post("/users/{user_id}/simulated")
def admin_set_simulated(
    user_id: int,
    body: SimulatedRequest,
    admin: dict = Depends(auth.require_admin),
) -> dict:
    try:
        with database.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="用户不存在")
            cur.execute(
                "UPDATE users SET is_simulated = %s WHERE id = %s",
                (body.is_simulated, user_id),
            )
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("admin simulated flag update failed")
        raise _db_error(exc) from exc
    return {
        "ok": True,
        "id": user_id,
        "is_simulated": body.is_simulated,
        "mode_name": "模拟交易账号" if body.is_simulated else "真实交易账号",
    }


@router.delete("/users/{user_id}")
def admin_delete_user(
    user_id: int,
    admin: dict = Depends(auth.require_admin),
) -> dict:
    try:
        with database.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="用户不存在")
            cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM trade_positions WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM trades WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("admin delete user failed")
        raise _db_error(exc) from exc
    return {"ok": True, "id": user_id}


@router.get("/logins")
def admin_logins(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    only_failed: bool = Query(default=False),
    admin: dict = Depends(auth.require_admin),
) -> dict:
    where = "WHERE success = 0" if only_failed else ""
    try:
        with database.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM login_logs {where}")
            total = int(cur.fetchone()["n"])
            cur.execute(
                f"""
                SELECT id, user_id, username, ip, success, message, created_at
                FROM login_logs
                {where}
                ORDER BY id DESC
                LIMIT %s OFFSET %s
                """,
                [page_size, (page - 1) * page_size],
            )
            rows = cur.fetchall()
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("login log list failed")
        raise _db_error(exc) from exc
    return {"total": total, "page": page, "page_size": page_size, "items": rows}


@router.get("/screens")
def admin_screens(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: dict = Depends(auth.require_admin),
) -> dict:
    try:
        with database.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM screen_runs")
            total = int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT r.id, r.user_id, u.username, r.capital, r.candidates,
                       r.allocations, r.summary, r.created_at
                FROM screen_runs r
                LEFT JOIN users u ON u.id = r.user_id
                ORDER BY r.id DESC
                LIMIT %s OFFSET %s
                """,
                [page_size, (page - 1) * page_size],
            )
            rows = cur.fetchall()
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("screen run list failed")
        raise _db_error(exc) from exc

    for row in rows:
        row["candidates"] = _json_load(row.get("candidates")) or []
        row["allocations"] = _json_load(row.get("allocations")) or []
        row["capital"] = float(row["capital"] or 0)
    return {"total": total, "page": page, "page_size": page_size, "items": rows}


@router.get("/trades")
def admin_trades(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: dict = Depends(auth.require_admin),
) -> dict:
    try:
        with database.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM trades")
            total = int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT t.id, t.user_id, u.username, t.mode, t.capital, t.cost,
                       t.market_value, t.profit, t.profit_pct, t.status,
                       t.created_at, t.updated_at
                FROM trades t
                LEFT JOIN users u ON u.id = t.user_id
                ORDER BY t.id DESC
                LIMIT %s OFFSET %s
                """,
                (page_size, (page - 1) * page_size),
            )
            rows = cur.fetchall()
            trade_ids = [int(row["id"]) for row in rows]
            positions: list[dict] = []
            if trade_ids:
                placeholders = ", ".join(["%s"] * len(trade_ids))
                cur.execute(
                    f"""
                    SELECT trade_id, symbol, name, shares, buy_price, cost,
                           last_price, market_value, profit
                    FROM trade_positions
                    WHERE trade_id IN ({placeholders})
                    ORDER BY id
                    """,
                    trade_ids,
                )
                positions = cur.fetchall()
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("trade list failed")
        raise _db_error(exc) from exc

    by_trade: dict[int, list[dict]] = {}
    for position in positions:
        for key in ("buy_price", "cost", "last_price", "market_value", "profit"):
            position[key] = float(position[key]) if position[key] is not None else None
        by_trade.setdefault(int(position["trade_id"]), []).append(position)

    for row in rows:
        for key in ("capital", "cost", "market_value", "profit", "profit_pct"):
            row[key] = float(row[key] or 0)
        row["mode_name"] = "模拟交易" if row["mode"] == "simulated" else "实盘交易"
        row["positions"] = by_trade.get(int(row["id"]), [])
    return {"total": total, "page": page, "page_size": page_size, "items": rows}
