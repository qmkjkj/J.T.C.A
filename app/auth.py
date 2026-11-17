from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from typing import Any

from fastapi import HTTPException, Request, Response

from . import database
from .config import (
    ADMIN_COOKIE,
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[\w.\-]{2,32}$", re.UNICODE)
PBKDF2_ITERATIONS = 260_000

VIP_NAMES = {0: "普通用户", 1: "黄金VIP", 2: "白金VIP", 3: "钻石VIP"}


def vip_name(level: Any) -> str:
    try:
        value = int(level)
    except (TypeError, ValueError):
        value = 0
    return VIP_NAMES.get(value, VIP_NAMES[0])

LOGIN_WINDOW_SECONDS = 600
LOGIN_MAX_FAILURES = 8
_attempt_lock = threading.Lock()
_login_attempts: dict[str, list[float]] = {}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = str(stored).split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except Exception:
        return False
    return hmac.compare_digest(actual, expected)


def validate_username(username: str) -> str:
    value = (username or "").strip()
    if not USERNAME_RE.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail="用户名需为 2-32 个字符，可用中文、字母、数字、下划线、点或短横线",
        )
    return value


def validate_password(password: str) -> str:
    if not isinstance(password, str) or not 6 <= len(password) <= 64:
        raise HTTPException(status_code=422, detail="密码长度需为 6-64 个字符")
    return password


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    user_id: int | None,
    is_admin: bool,
    ip: str = "",
    user_agent: str = "",
) -> str:
    token = secrets.token_urlsafe(32)
    with database.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE expires_at <= NOW()")
        cur.execute(
            """
            INSERT INTO sessions
                (token_hash, user_id, is_admin, created_at, expires_at, ip, user_agent)
            VALUES (%s, %s, %s, NOW(), DATE_ADD(NOW(), INTERVAL %s SECOND), %s, %s)
            """,
            (
                _hash_token(token),
                user_id,
                1 if is_admin else 0,
                SESSION_TTL_SECONDS,
                ip[:64],
                user_agent[:255],
            ),
        )
    return token


def delete_session(token: str | None) -> None:
    if not token:
        return
    with database.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token_hash = %s", (_hash_token(token),))


def delete_user_sessions(user_id: int) -> None:
    with database.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


def resolve_session(token: str | None, admin: bool) -> dict[str, Any] | None:
    if not token:
        return None
    with database.cursor() as cur:
        cur.execute(
            """
            SELECT s.user_id, s.is_admin, u.username, u.status, u.vip_level,
                   u.balance, u.is_simulated
            FROM sessions s
            LEFT JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = %s AND s.expires_at > NOW()
            """,
            (_hash_token(token),),
        )
        row = cur.fetchone()
    if not row:
        return None
    if bool(row["is_admin"]) != admin:
        return None
    if admin:
        return {"user_id": None, "username": ADMIN_USERNAME, "is_admin": True}
    if row["user_id"] is None or row["status"] != 1:
        try:
            delete_session(token)
        except Exception:
            logger.warning("failed to clear stale session", exc_info=True)
        return None
    level = int(row.get("vip_level") or 0)
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "is_admin": False,
        "vip_level": level,
        "vip_name": vip_name(level),
        "balance": round(float(row.get("balance") or 0), 2),
        "is_simulated": bool(row.get("is_simulated")),
    }


def user_session_from_request(request: Request) -> dict[str, Any] | None:
    return resolve_session(request.cookies.get(SESSION_COOKIE), admin=False)


def admin_session_from_request(request: Request) -> dict[str, Any] | None:
    return resolve_session(request.cookies.get(ADMIN_COOKIE), admin=True)


def require_user(request: Request) -> dict[str, Any]:
    session = user_session_from_request(request)
    if not session:
        raise HTTPException(status_code=401, detail="请先登录")
    return session


def require_admin(request: Request) -> dict[str, Any]:
    session = admin_session_from_request(request)
    if not session:
        raise HTTPException(status_code=401, detail="请先登录后台")
    return session


def set_user_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_user_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def set_admin_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        ADMIN_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(ADMIN_COOKIE, path="/")


def verify_admin_credentials(username: str, password: str) -> bool:
    given_user = (username or "").strip().encode("utf-8")
    given_pass = (password or "").encode("utf-8")
    return hmac.compare_digest(
        given_user, ADMIN_USERNAME.encode("utf-8")
    ) and hmac.compare_digest(given_pass, ADMIN_PASSWORD.encode("utf-8"))


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def client_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:255]


def login_rate_key(request: Request, username: str) -> str:
    return f"{client_ip(request)}:{(username or '').strip().lower()}"


def check_login_rate(key: str) -> None:
    now = time.time()
    with _attempt_lock:
        entries = [item for item in _login_attempts.get(key, []) if now - item < LOGIN_WINDOW_SECONDS]
        _login_attempts[key] = entries
        if len(entries) >= LOGIN_MAX_FAILURES:
            raise HTTPException(
                status_code=429, detail="登录尝试过多，请 10 分钟后再试"
            )


def record_login_failure(key: str) -> None:
    with _attempt_lock:
        _login_attempts.setdefault(key, []).append(time.time())


def clear_login_failures(key: str) -> None:
    with _attempt_lock:
        _login_attempts.pop(key, None)


def log_login(
    request: Request,
    username: str,
    success: bool,
    user_id: int | None = None,
    message: str = "",
) -> None:
    try:
        with database.cursor() as cur:
            cur.execute(
                """
                INSERT INTO login_logs
                    (user_id, username, ip, user_agent, success, message, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    user_id,
                    (username or "")[:64],
                    client_ip(request),
                    client_agent(request),
                   1 if success else 0,
                    message[:160],
                ),
            )
    except Exception:
        logger.warning("failed to write login log", exc_info=True)
