from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor

from .config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

logger = logging.getLogger(__name__)


class DatabaseUnavailable(RuntimeError):
    pass


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        username VARCHAR(64) NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        status TINYINT NOT NULL DEFAULT 1,
        vip_level TINYINT NOT NULL DEFAULT 0,
        balance DECIMAL(16,2) NOT NULL DEFAULT 0,
        is_simulated TINYINT NOT NULL DEFAULT 1,
        created_at DATETIME NOT NULL,
        last_login_at DATETIME NULL,
        PRIMARY KEY (id),
        UNIQUE KEY uk_users_username (username)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash CHAR(64) NOT NULL,
        user_id BIGINT UNSIGNED NULL,
        is_admin TINYINT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL,
        expires_at DATETIME NOT NULL,
        ip VARCHAR(64) NULL,
        user_agent VARCHAR(255) NULL,
        PRIMARY KEY (token_hash),
        KEY idx_sessions_expires (expires_at),
        KEY idx_sessions_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS login_logs (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        user_id BIGINT UNSIGNED NULL,
        username VARCHAR(64) NOT NULL,
        ip VARCHAR(64) NULL,
        user_agent VARCHAR(255) NULL,
        success TINYINT NOT NULL DEFAULT 0,
        message VARCHAR(160) NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        KEY idx_login_created (created_at),
        KEY idx_login_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS screen_runs (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        user_id BIGINT UNSIGNED NULL,
        capital DECIMAL(16,2) NOT NULL DEFAULT 0,
        candidates TEXT NULL,
        allocations TEXT NULL,
        summary TEXT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        KEY idx_screen_created (created_at),
        KEY idx_screen_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        user_id BIGINT UNSIGNED NOT NULL,
        mode VARCHAR(16) NOT NULL DEFAULT 'simulated',
        capital DECIMAL(16,2) NOT NULL DEFAULT 0,
        cost DECIMAL(16,2) NOT NULL DEFAULT 0,
        market_value DECIMAL(16,2) NOT NULL DEFAULT 0,
        profit DECIMAL(16,2) NOT NULL DEFAULT 0,
        profit_pct DECIMAL(10,4) NOT NULL DEFAULT 0,
        status VARCHAR(16) NOT NULL DEFAULT 'open',
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        KEY idx_trades_created (created_at),
        KEY idx_trades_user (user_id),
        KEY idx_trades_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS trade_positions (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        trade_id BIGINT UNSIGNED NOT NULL,
        user_id BIGINT UNSIGNED NOT NULL,
        symbol VARCHAR(16) NOT NULL,
        name VARCHAR(64) NULL,
        shares INT UNSIGNED NOT NULL,
        buy_price DECIMAL(16,4) NOT NULL,
        cost DECIMAL(16,2) NOT NULL,
        last_price DECIMAL(16,4) NULL,
        market_value DECIMAL(16,2) NULL,
        profit DECIMAL(16,2) NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        KEY idx_positions_trade (trade_id),
        KEY idx_positions_user (user_id),
        KEY idx_positions_symbol (symbol)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_watch_settings (
        user_id BIGINT UNSIGNED NOT NULL,
        enabled TINYINT NOT NULL DEFAULT 0,
        strategy TINYINT UNSIGNED NOT NULL DEFAULT 50,
        last_run_at DATETIME NULL,
        last_result LONGTEXT NULL,
        last_error VARCHAR(500) NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (user_id),
        KEY idx_ai_watch_enabled (enabled)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS trade_realized (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        user_id BIGINT UNSIGNED NOT NULL,
        trade_id BIGINT UNSIGNED NOT NULL,
        symbol VARCHAR(16) NOT NULL,
        name VARCHAR(64) NULL,
        shares INT UNSIGNED NOT NULL,
        buy_price DECIMAL(16,4) NOT NULL,
        sale_price DECIMAL(16,4) NOT NULL,
        cost DECIMAL(16,2) NOT NULL,
        proceeds DECIMAL(16,2) NOT NULL,
        profit DECIMAL(16,2) NOT NULL,
        today_profit DECIMAL(16,2) NOT NULL DEFAULT 0,
        month_profit DECIMAL(16,2) NOT NULL DEFAULT 0,
        trade_date DATE NOT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        KEY idx_realized_user (user_id, trade_date),
        KEY idx_realized_symbol (user_id, symbol)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

MIGRATIONS = [
    (
        "users",
        "vip_level",
        "ALTER TABLE users ADD COLUMN vip_level TINYINT NOT NULL DEFAULT 0 AFTER status",
    ),
    (
        "users",
        "balance",
        "ALTER TABLE users ADD COLUMN balance DECIMAL(16,2) NOT NULL DEFAULT 0 AFTER vip_level",
    ),
    (
        "users",
        "is_simulated",
        "ALTER TABLE users ADD COLUMN is_simulated TINYINT NOT NULL DEFAULT 1 AFTER balance",
    ),
]

_schema_lock = threading.Lock()
_schema_ready = False


def _apply_migrations(cur: DictCursor) -> None:
    for table, column, statement in MIGRATIONS:
        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
            """,
            (DB_NAME, table, column),
        )
        if int(cur.fetchone()["n"]) == 0:
            cur.execute(statement)
            logger.info("applied migration %s.%s", table, column)


def is_configured() -> bool:
    return bool(DB_HOST and DB_USER and DB_NAME)


def connect() -> pymysql.connections.Connection:
    if not is_configured():
        raise DatabaseUnavailable("数据库未配置")
    try:
        return pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=True,
            connect_timeout=8,
            read_timeout=15,
            write_timeout=15,
        )
    except Exception as exc:
        raise DatabaseUnavailable(f"数据库连接失败: {exc}") from exc


@contextmanager
def cursor() -> Iterator[DictCursor]:
    connection = connect()
    try:
        with connection.cursor() as cur:
            yield cur
    finally:
        connection.close()


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with cursor() as cur:
            for statement in SCHEMA_STATEMENTS:
                cur.execute(statement)
            _apply_migrations(cur)
        _schema_ready = True
        logger.info("database schema ready")
