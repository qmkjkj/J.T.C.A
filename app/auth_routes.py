from __future__ import annotations

import logging

import pymysql
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import auth, database
from .config import ADMIN_USERNAME, SESSION_COOKIE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=128)


def _db_error(exc: Exception) -> HTTPException:
    logger.warning("auth database error: %s", exc)
    return HTTPException(status_code=503, detail="账号服务暂不可用，请稍后重试")


def _user_payload(
    user_id: int,
    username: str,
    vip_level: int = 0,
    is_simulated: int | bool = 1,
    balance: float = 0,
) -> dict:
    level = int(vip_level or 0)
    return {
        "user_id": user_id,
        "username": username,
        "is_admin": False,
        "vip_level": level,
        "vip_name": auth.vip_name(level),
        "balance": round(float(balance or 0), 2),
        "is_simulated": bool(is_simulated),
    }


@router.post("/register")
def register(request: Request, response: Response, body: Credentials) -> dict:
    username = auth.validate_username(body.username)
    password = auth.validate_password(body.password)
    if username.lower() == ADMIN_USERNAME.lower():
        raise HTTPException(status_code=409, detail="该用户名不可用")

    try:
        database.ensure_schema()
        with database.cursor() as cur:
            cur.execute(
                "SELECT id, status FROM users WHERE username = %s",
                (username,),
            )
            existing = cur.fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="该用户名已被注册")
            cur.execute(
                """
                INSERT INTO users (username, password_hash, status, created_at, last_login_at)
                VALUES (%s, %s, 1, NOW(), NOW())
                """,
                (username, auth.hash_password(password)),
            )
            user_id = cur.lastrowid
    except HTTPException:
        raise
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except pymysql.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="该用户名已被注册") from exc
    except Exception as exc:
        logger.exception("register failed")
        raise _db_error(exc) from exc

    try:
        token = auth.create_session(
            user_id, False, auth.client_ip(request), auth.client_agent(request)
        )
    except Exception as exc:
        logger.exception("session creation failed")
        raise _db_error(exc) from exc

    auth.set_user_cookie(response, token)
    auth.log_login(request, username, True, user_id, "注册并登录")
    return {"ok": True, "user": _user_payload(user_id, username)}


@router.post("/login")
def login(request: Request, response: Response, body: Credentials) -> dict:
    username = (body.username or "").strip()
    password = body.password or ""
    if not username or not password:
        raise HTTPException(status_code=422, detail="请输入用户名和密码")

    rate_key = auth.login_rate_key(request, username)
    auth.check_login_rate(rate_key)

    try:
        database.ensure_schema()
        with database.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, password_hash, status, vip_level, balance, is_simulated
                FROM users WHERE username = %s
                """,
                (username,),
            )
            row = cur.fetchone()
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("login query failed")
        raise _db_error(exc) from exc

    if not row or not auth.verify_password(password, row["password_hash"]):
        auth.record_login_failure(rate_key)
        auth.log_login(request, username, False, row["id"] if row else None, "用户名或密码错误")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if row["status"] != 1:
        auth.record_login_failure(rate_key)
        auth.log_login(request, username, False, row["id"], "账号已停用")
        raise HTTPException(status_code=403, detail="该账号已被停用，请联系管理员")

    auth.clear_login_failures(rate_key)
    try:
        token = auth.create_session(
            row["id"], False, auth.client_ip(request), auth.client_agent(request)
        )
        with database.cursor() as cur:
            cur.execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", (row["id"],))
    except Exception as exc:
        logger.exception("session creation failed")
        raise _db_error(exc) from exc

    auth.set_user_cookie(response, token)
    auth.log_login(request, row["username"], True, row["id"], "登录成功")
    return {
        "ok": True,
        "user": _user_payload(
            row["id"],
            row["username"],
            row.get("vip_level"),
            row.get("is_simulated", 1),
            row.get("balance", 0),
        ),
    }


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    try:
        auth.delete_session(token)
    except Exception:
        logger.warning("failed to delete session", exc_info=True)
    auth.clear_user_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    try:
        session = auth.user_session_from_request(request)
    except database.DatabaseUnavailable as exc:
        raise _db_error(exc) from exc
    except Exception as exc:
        logger.exception("session lookup failed")
        raise _db_error(exc) from exc
    if not session:
        raise HTTPException(status_code=401, detail="请先登录")
    return {"ok": True, "user": session}
