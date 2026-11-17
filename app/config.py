from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"

load_dotenv(BASE_DIR / ".env")

APP_NAME = "J.T.C.A"
APP_SUBTITLE = "A股量化分析工具"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()
DEEPSEEK_REASONING_EFFORT = os.getenv("DEEPSEEK_REASONING_EFFORT", "max").strip().lower()
if DEEPSEEK_REASONING_EFFORT not in {"low", "high", "max"}:
    DEEPSEEK_REASONING_EFFORT = "max"

MAX_SELECTION = int(os.getenv("MAX_SELECTION", "5"))

# Remote MySQL database
DB_HOST = os.getenv("DB_HOST", "").strip()
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "").strip()
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "").strip()

# Local accounts
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "qmkjkj").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "qmkjkj")
ADMIN_PATH = "/qmkjkj"
ADMIN_UI_DIR = BASE_DIR / "admin_ui"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_HOURS", "168")) * 3600
SESSION_COOKIE = "jt_session"
ADMIN_COOKIE = "jt_admin_session"

DEFAULT_WATCHLIST = [
    "600519.SS",
    "300750.SZ",
    "601318.SS",
    "000858.SZ",
    "002594.SZ",
    "600036.SS",
]

DEFAULT_SELECTED: list[str] = []

MARKET_SYMBOLS = ["000001.SS", "399001.SZ", "399006.SZ", "000300.SS"]

DISCLAIMER = (
    "行情与新闻来自公开数据接口，可能存在延迟或缺失。AI 输出仅用于研究与信息整理，"
    "不构成任何投资建议，也不应作为交易依据。"
)

HK_DEFAULT_WATCHLIST = [
    "00700.HK",
    "09988.HK",
    "03690.HK",
    "01810.HK",
    "00941.HK",
    "00388.HK",
]

HK_MARKET_SYMBOLS = ["^HSI", "^HSCE", "^HSTECH"]

# 平台元数据：前端顶部的平台切换与后端接口共用。
PLATFORMS = {
    "CN": {
        "app_name": APP_NAME,
        "subtitle": APP_SUBTITLE,
        "model": "J.T.C.A AI",
        "market_label": "A 股市场",
        "market_short": "A股",
        "currency": "CNY",
        "currency_symbol": "¥",
        "currency_name": "人民币",
        "default_watchlist": DEFAULT_WATCHLIST,
        "market_symbols": MARKET_SYMBOLS,
        "providers": ["东方财富", "腾讯财经", "Yahoo Finance"],
        "session_note": "北京时间 09:30-11:30 / 13:00-15:00",
        "lot_note": "A 股每手 100 股",
        "rule_note": "T+1、涨跌停限制",
        "disclaimer": DISCLAIMER,
    },
    "HK": {
        "app_name": "J.T.C.G",
        "subtitle": "港股量化分析工具",
        "model": "J.T.C.G AI",
        "market_label": "港股市场",
        "market_short": "港股",
        "currency": "HKD",
        "currency_symbol": "HK$",
        "currency_name": "港币",
        "default_watchlist": HK_DEFAULT_WATCHLIST,
        "market_symbols": HK_MARKET_SYMBOLS,
        "providers": ["东方财富", "腾讯财经", "Yahoo Finance"],
        "session_note": "香港时间 09:30-12:00 / 13:00-16:00",
        "lot_note": "港股每手股数因股票而异",
        "rule_note": "T+0 回转交易、无涨跌停限制",
        "disclaimer": DISCLAIMER,
    },
}


def platform_meta(platform: str | None) -> dict:
    key = (platform or "CN").strip().upper()
    return PLATFORMS.get(key, PLATFORMS["CN"])
