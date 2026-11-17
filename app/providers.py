from __future__ import annotations

import html
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, TypeVar
from urllib.parse import quote as url_quote, urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import yfinance as yf

from .cache import CircuitBreaker, TTLCache
from .universe import (
    HK_INDEX_SYMBOLS,
    display_name,
    is_valid_symbol,
    lot_size,
    lookup,
    normalize_symbol,
)

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

T = TypeVar("T")

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_HTTP = httpx.Client(
    headers=_HTTP_HEADERS,
    follow_redirects=True,
    timeout=httpx.Timeout(20.0, connect=10.0),
)

_cache = TTLCache()
_yf_circuit = CircuitBreaker(failure_threshold=2, open_seconds=300.0)
_bundle_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_probe_lock = threading.Lock()


def _call_with_timeout(fn: Callable[[], T], timeout: float) -> T:
    """Run a possibly blocking yfinance call behind a hard deadline.

    yfinance's own timeout does not cover every internal request. A daemon thread
    prevents a blocked Yahoo endpoint from freezing the web request.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # propagate to caller
            box["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"Yahoo request exceeded {timeout:.0f}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _yahoo_reachable() -> bool:
    """Fast connectivity probe before handing work to yfinance."""
    cached = _cache.get("yf:reachable")
    if cached is not None:
        return bool(cached)
    with _probe_lock:
        cached = _cache.get("yf:reachable")
        if cached is not None:
            return bool(cached)
        ok = False
        try:
            response = httpx.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
                params={"range": "1d", "interval": "1d"},
                headers=_HTTP_HEADERS,
                follow_redirects=True,
                timeout=4.0,
            )
            content = response.content[:2000]
            ok = response.status_code == 200 and b'"chart"' in content
        except Exception as exc:
            logger.info("Yahoo connectivity probe failed: %s", exc)
        _cache.set("yf:reachable", ok, 300.0 if ok else 180.0)
        if not ok:
            _yf_circuit.open_for(300.0)
        return ok


def _yf_allowed() -> bool:
    if not _yf_circuit.allow():
        return False
    return _yahoo_reachable()

_INDEX_TO_TENCENT = {
    "000001.SS": "sh000001",
    "399001.SZ": "sz399001",
    "399006.SZ": "sz399006",
    "000300.SS": "sh000300",
    "^HSI": "hkHSI",
    "^HSCE": "hkHSCEI",
    "^HSTECH": "hkHSTECH",
}
_US_ZONE = ZoneInfo("America/New_York")
_HK_ZONE = ZoneInfo("Asia/Hong_Kong")
_CN_ZONE = ZoneInfo("Asia/Shanghai")

_CN_SUFFIXES = (".SS", ".SZ", ".BJ")

_NEWS_WINDOW_DAYS = 31

_EASTMONEY_QUOTE_FIELDS = (
    "f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,"
    "f116,f117,f162,f167,f168,f169,f170,f50"
)


def _is_cn_symbol(symbol: str) -> bool:
    return symbol.upper().endswith(_CN_SUFFIXES)


def _is_hk_symbol(symbol: str) -> bool:
    upper = symbol.upper()
    return upper.endswith(".HK") or upper in HK_INDEX_SYMBOLS


def _cn_code(symbol: str) -> str:
    return symbol.upper().rsplit(".", 1)[0]


def _cn_exchange(symbol: str) -> str:
    upper = symbol.upper()
    if upper.endswith(".SS"):
        return "SSE"
    if upper.endswith(".SZ"):
        return "SZSE"
    if upper.endswith(".BJ"):
        return "BSE"
    return "CN"


def _exchange_label(symbol: str) -> str:
    if _is_cn_symbol(symbol):
        return _cn_exchange(symbol)
    if _is_hk_symbol(symbol):
        return "HKEX"
    return ""


def _default_currency(symbol: str) -> str:
    upper = symbol.upper()
    if upper.endswith(_CN_SUFFIXES):
        return "CNY"
    if _is_hk_symbol(symbol):
        return "HKD"
    return "USD"


def _market_close(symbol: str) -> tuple[ZoneInfo, time]:
    upper = symbol.upper()
    if upper.endswith(_CN_SUFFIXES):
        return _CN_ZONE, time(15, 0)
    if _is_hk_symbol(symbol):
        return _HK_ZONE, time(16, 0)
    return _US_ZONE, time(16, 0)


_HK_INDEX_SECIDS = {
    "^HSI": "100.HSI",
    "^HSCE": "100.HSCEI",
    "^HSTECH": "100.HSTECH",
}


def _eastmoney_secid(symbol: str) -> str:
    upper = symbol.upper()
    if upper in _HK_INDEX_SECIDS:
        return _HK_INDEX_SECIDS[upper]
    if upper.endswith(".HK"):
        return f"116.{_cn_code(symbol).zfill(5)}"
    code = _cn_code(symbol)
    if upper.endswith(".SS"):
        return f"1.{code}"
    return f"0.{code}"


class MarketDataError(RuntimeError):
    pass


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_attr(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _bundle_lock(symbol: str) -> threading.Lock:
    with _locks_guard:
        return _bundle_locks.setdefault(symbol, threading.Lock())


def _market_session(symbol: str) -> str:
    upper = symbol.upper()
    now_utc = datetime.now(timezone.utc)
    try:
        if upper.endswith(_CN_SUFFIXES):
            now = now_utc.astimezone(_CN_ZONE)
            current = now.time()
            if now.weekday() < 5 and (
                time(9, 30) <= current < time(11, 30) or time(13, 0) <= current < time(15, 0)
            ):
                return "盘中"
        elif _is_hk_symbol(symbol):
            now = now_utc.astimezone(_HK_ZONE)
            current = now.time()
            if now.weekday() < 5 and (
                time(9, 30) <= current < time(12, 0) or time(13, 0) <= current < time(16, 0)
            ):
                return "盘中"
        else:
            now = now_utc.astimezone(_US_ZONE)
            if now.weekday() < 5 and time(9, 30) <= now.time() < time(16, 0):
                return "盘中"
    except Exception:
        pass
    return "休市"


def _quote_timezone(symbol: str) -> str:
    upper = symbol.upper()
    if _is_hk_symbol(symbol):
        return "HKT"
    if upper.endswith(_CN_SUFFIXES):
        return "CST"
    return "ET"


def _clean_text(value: Any, limit: int = 700) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if re.match(r"^[A-Za-z]{3},", text):
            parsed = parsedate_to_datetime(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _news_is_recent(published: datetime | None) -> bool:
    if published is None:
        return True
    return published >= datetime.now(timezone.utc) - timedelta(days=_NEWS_WINDOW_DAYS)


def _dedupe_news(items: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for item in items:
        title = re.sub(r"\s+", " ", str(item.get("title", ""))).strip()
        if not title:
            continue
        key = title.lower()
        current = best.get(key)
        if current is None or len(item.get("summary", "")) > len(current.get("summary", "")):
            best[key] = item
    result = list(best.values())
    result.sort(
        key=lambda item: item.get("published_at") or "",
        reverse=True,
    )
    return result


def _publisher_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    known = {
        "finance.yahoo.com": "Yahoo Finance",
        "reuters.com": "Reuters",
        "cnbc.com": "CNBC",
        "bloomberg.com": "Bloomberg",
        "marketwatch.com": "MarketWatch",
        "barrons.com": "Barron's",
        "investors.com": "Investor's Business Daily",
        "ft.com": "Financial Times",
        "wsj.com": "The Wall Street Journal",
        "businessinsider.com": "Business Insider",
        "benzinga.com": "Benzinga",
        "seekingalpha.com": "Seeking Alpha",
    }
    return known.get(host, host or "Yahoo Finance")


def _normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise MarketDataError("历史行情为空")
    frame = df.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [str(col[0]) for col in frame.columns]
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise MarketDataError(f"历史行情缺少字段: {', '.join(missing)}")
    frame = frame[required].copy()
    frame.index = pd.to_datetime(frame.index)
    if getattr(frame.index, "tz", None) is not None:
        frame.index = frame.index.tz_localize(None)
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
    frame["Volume"] = frame["Volume"].fillna(0)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    if frame.empty:
        raise MarketDataError("历史行情为空")
    return frame


def _quote_from_history(
    symbol: str,
    history: pd.DataFrame,
    *,
    name: str,
    source: str,
    currency: str = "USD",
    exchange: str | None = None,
) -> dict:
    last = history.iloc[-1]
    previous = history.iloc[-2] if len(history) > 1 else last
    price = _to_float(last["Close"]) or 0.0
    previous_close = _to_float(previous["Close"]) or price
    change = price - previous_close
    change_pct = (change / previous_close * 100) if previous_close else 0.0
    last_date = history.index[-1].to_pydatetime()
    close_zone, close_time = _market_close(symbol)
    quote_time = datetime.combine(last_date.date(), close_time, tzinfo=close_zone)
    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 4),
        "previous_close": round(previous_close, 4),
        "open": round(_to_float(last["Open"]) or price, 4),
        "day_high": round(_to_float(last["High"]) or price, 4),
        "day_low": round(_to_float(last["Low"]) or price, 4),
        "volume": _to_int(last["Volume"]),
        "market_cap": None,
        "pe": None,
        "high_52w": round(float(history["High"].tail(252).max()), 4),
        "low_52w": round(float(history["Low"].tail(252).min()), 4),
        "currency": currency,
        "exchange": exchange,
        "session": _market_session(symbol),
        "quote_time": quote_time.isoformat(),
        "quote_timezone": _quote_timezone(symbol),
        "source": source,
    }


# ---------------------------------------------------------------------------
# Yahoo Finance via yfinance (primary)
# ---------------------------------------------------------------------------


def _yf_ticker_symbol(symbol: str) -> str:
    """Yahoo 的港股代码为 4 位数字（如 0700.HK），内部统一存 5 位。"""
    if symbol.upper().endswith(".HK"):
        code = symbol.upper().rsplit(".", 1)[0]
        return f"{code.lstrip('0').zfill(4)}.HK"
    return symbol


def _yf_history_and_quote(symbol: str) -> tuple[pd.DataFrame, dict]:
    ticker = yf.Ticker(_yf_ticker_symbol(symbol))
    frame = ticker.history(
        period="2y",
        interval="1d",
        auto_adjust=True,
        actions=False,
        timeout=10,
    )
    history = _normalize_history(frame)

    price = None
    previous_close = None
    open_price = None
    day_high = None
    day_low = None
    volume = None
    market_cap = None
    currency = None
    exchange = None
    try:
        fast = ticker.fast_info
        price = _to_float(_safe_attr(fast, "last_price"))
        previous_close = _to_float(_safe_attr(fast, "previous_close"))
        open_price = _to_float(_safe_attr(fast, "open"))
        day_high = _to_float(_safe_attr(fast, "day_high"))
        day_low = _to_float(_safe_attr(fast, "day_low"))
        volume = _to_int(_safe_attr(fast, "last_volume"))
        market_cap = _to_float(_safe_attr(fast, "market_cap"))
        currency = _safe_attr(fast, "currency")
        exchange = _safe_attr(fast, "exchange")
    except Exception as exc:  # fast_info is best effort
        logger.debug("fast_info failed for %s: %s", symbol, exc)

    last = history.iloc[-1]
    if not price:
        price = _to_float(last["Close"])
    if not previous_close:
        previous_close = _to_float(history.iloc[-2]["Close"]) if len(history) > 1 else price
    if not open_price:
        open_price = _to_float(last["Open"])
    if day_high is None:
        day_high = _to_float(last["High"])
    if day_low is None:
        day_low = _to_float(last["Low"])
    if volume is None:
        volume = _to_int(last["Volume"])
    if not currency:
        currency = _default_currency(symbol)

    price = float(price or 0)
    previous_close = float(previous_close or price)
    change = price - previous_close
    change_pct = (change / previous_close * 100) if previous_close else 0.0
    last_date = history.index[-1].to_pydatetime()
    close_zone, close_time = _market_close(symbol)
    quote_date = datetime.combine(last_date.date(), close_time, tzinfo=close_zone)
    if _market_session(symbol) == "盘中":
        quote_date = datetime.now(timezone.utc)

    item = lookup(symbol)
    name = item["name"] if item else display_name(symbol)
    quote = {
        "symbol": symbol,
        "name": name,
        "price": round(price, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 4),
        "previous_close": round(previous_close, 4),
        "open": round(float(open_price or price), 4),
        "day_high": round(float(day_high or price), 4),
        "day_low": round(float(day_low or price), 4),
        "volume": volume,
        "market_cap": market_cap,
        "pe": None,
        "high_52w": round(float(history["High"].tail(252).max()), 4),
        "low_52w": round(float(history["Low"].tail(252).min()), 4),
        "currency": currency,
        "exchange": exchange,
        "session": _market_session(symbol),
        "quote_time": quote_date.isoformat(),
        "quote_timezone": _quote_timezone(symbol),
        "source": "Yahoo Finance",
    }
    return history, quote


def _yf_quote(symbol: str) -> dict:
    ticker = yf.Ticker(_yf_ticker_symbol(symbol))
    fast = ticker.fast_info
    price = _to_float(_safe_attr(fast, "last_price"))
    previous_close = _to_float(_safe_attr(fast, "previous_close"))
    if price is None:
        raise MarketDataError("Yahoo 未返回最新价")
    if previous_close is None:
        previous_close = price
    change = price - previous_close
    change_pct = (change / previous_close * 100) if previous_close else 0.0
    item = lookup(symbol)
    name = item["name"] if item else display_name(symbol)
    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 4),
        "previous_close": round(previous_close, 4),
        "open": round(float(_to_float(_safe_attr(fast, "open")) or price), 4),
        "day_high": round(float(_to_float(_safe_attr(fast, "day_high")) or price), 4),
        "day_low": round(float(_to_float(_safe_attr(fast, "day_low")) or price), 4),
        "volume": _to_int(_safe_attr(fast, "last_volume")),
        "market_cap": _to_float(_safe_attr(fast, "market_cap")),
        "pe": None,
        "high_52w": _to_float(_safe_attr(fast, "year_high")),
        "low_52w": _to_float(_safe_attr(fast, "year_low")),
        "currency": _safe_attr(fast, "currency") or _default_currency(symbol),
        "exchange": _safe_attr(fast, "exchange"),
        "session": _market_session(symbol),
        "quote_time": datetime.now(timezone.utc).isoformat(),
        "quote_timezone": _quote_timezone(symbol),
        "source": "Yahoo Finance",
    }


def _yf_news(symbol: str) -> list[dict]:
    ticker = yf.Ticker(_yf_ticker_symbol(symbol))
    raw_items = ticker.news or []
    items: list[dict] = []
    for raw in raw_items:
        content = raw.get("content") if isinstance(raw, dict) else None
        if isinstance(content, dict):
            title = _clean_text(content.get("title"), 300)
            summary = _clean_text(
                content.get("summary") or content.get("description"), 700
            )
            published = _parse_datetime(content.get("pubDate") or content.get("displayTime"))
            provider = content.get("provider") or {}
            publisher = _clean_text(provider.get("displayName"), 100) or "Yahoo Finance"
            canonical = content.get("canonicalUrl") or {}
            click = content.get("clickThroughUrl") or {}
            url = canonical.get("url") or click.get("url") or ""
            thumbnail = ""
            thumb = content.get("thumbnail") or {}
            resolutions = thumb.get("resolutions") or []
            if resolutions:
                thumbnail = resolutions[-1].get("url") or ""
        elif isinstance(raw, dict):
            title = _clean_text(raw.get("title"), 300)
            summary = _clean_text(raw.get("summary") or raw.get("description"), 700)
            published = _parse_datetime(raw.get("providerPublishTime"))
            publisher = _clean_text(raw.get("publisher"), 100) or "Yahoo Finance"
            url = raw.get("link") or ""
            thumbnail = ""
            resolutions = (raw.get("thumbnail") or {}).get("resolutions") or []
            if resolutions:
                thumbnail = resolutions[-1].get("url") or ""
        else:
            continue
        if not title:
            continue
        if not _news_is_recent(published):
            continue
        items.append(
            {
                "title": title,
                "summary": summary,
                "url": url,
                "publisher": publisher,
                "published_at": published.isoformat() if published else None,
                "thumbnail": thumbnail,
                "symbol": symbol,
                "source": "Yahoo Finance",
            }
        )
    return _dedupe_news(items)


# ---------------------------------------------------------------------------
# Eastmoney (primary for A-shares: quote, two-year daily history, news)
# ---------------------------------------------------------------------------


def _eastmoney_scaled(data: dict, key: str, decimals: int | None = None) -> float | None:
    """东方财富价格字段按 f59 指定的小数位缩放，百分比/估值字段固定 2 位。"""
    value = _to_float(data.get(key))
    if value is None:
        return None
    if decimals is None:
        digits = _to_int(data.get("f59"))
        decimals = 2 if digits is None else max(0, min(digits, 6))
    return value / (10.0**decimals)


def _eastmoney_quote(symbol: str) -> dict:
    response = _HTTP.get(
        "https://push2.eastmoney.com/api/qt/stock/get",
        params={"secid": _eastmoney_secid(symbol), "fields": _EASTMONEY_QUOTE_FIELDS},
    )
    response.raise_for_status()
    data = (response.json() or {}).get("data")
    if not data:
        raise MarketDataError("东方财富未返回该代码")

    price = _eastmoney_scaled(data, "f43")
    if price is None:
        raise MarketDataError("东方财富未返回最新价")
    previous_close = _eastmoney_scaled(data, "f60")
    if previous_close is None:
        previous_close = price
    change = _eastmoney_scaled(data, "f169")
    if change is None:
        change = price - previous_close
    change_pct = _eastmoney_scaled(data, "f170", 2)
    if change_pct is None:
        change_pct = (change / previous_close * 100) if previous_close else 0.0

    item = lookup(symbol)
    raw_name = _clean_text(data.get("f58"), 120)
    name = raw_name or (item["name"] if item else display_name(symbol))
    pe = _eastmoney_scaled(data, "f162", 2)
    if pe is not None and pe <= 0:
        pe = None
    market_cap = _to_float(data.get("f116"))
    if market_cap is not None and market_cap <= 0:
        market_cap = None

    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 4),
        "previous_close": round(previous_close, 4),
        "open": round(_eastmoney_scaled(data, "f46") or price, 4),
        "day_high": round(_eastmoney_scaled(data, "f44") or price, 4),
        "day_low": round(_eastmoney_scaled(data, "f45") or price, 4),
        "volume": _to_int(data.get("f47")),
        "market_cap": market_cap,
        "pe": pe,
        "high_52w": None,
        "low_52w": None,
        "currency": _default_currency(symbol),
        "exchange": _exchange_label(symbol),
        "session": _market_session(symbol),
        "quote_time": datetime.now(timezone.utc).isoformat(),
        "quote_timezone": _quote_timezone(symbol),
        "source": "东方财富",
    }


def _eastmoney_history(symbol: str) -> pd.DataFrame:
    response = _HTTP.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": _eastmoney_secid(symbol),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56",
            "klt": "101",
            "fqt": "1",
            "beg": "0",
            "end": "20500101",
            "lmt": "520",
        },
    )
    response.raise_for_status()
    data = (response.json() or {}).get("data") or {}
    klines = data.get("klines") or []
    if not klines:
        raise MarketDataError("东方财富未返回历史行情")

    cutoff = (date.today() - timedelta(days=732)).isoformat()
    rows: list[dict] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        day = parts[0]
        if not day or day < cutoff:
            continue
        open_price = _to_float(parts[1])
        close_price = _to_float(parts[2])
        if open_price is None or close_price is None:
            continue
        rows.append(
            {
                "Date": day,
                "Open": open_price,
                "High": _to_float(parts[3]),
                "Low": _to_float(parts[4]),
                "Close": close_price,
                "Volume": _to_float(parts[5]) or 0,
            }
        )
    if not rows:
        raise MarketDataError("东方财富未返回最近两年的历史行情")
    frame = pd.DataFrame(rows).set_index("Date")
    frame.index = pd.to_datetime(frame.index)
    return _normalize_history(frame)


def _eastmoney_trends(symbol: str, ndays: int = 5) -> dict:
    """东方财富分时数据：最近若干交易日的 1 分钟 OHLC。"""
    response = _HTTP.get(
        "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
        params={
            "secid": _eastmoney_secid(symbol),
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "iscr": "0",
            "ndays": str(max(1, min(int(ndays), 5))),
        },
    )
    response.raise_for_status()
    data = (response.json() or {}).get("data") or {}
    trends = data.get("trends") or []
    if not trends:
        raise MarketDataError("东方财富未返回分时行情")

    rows: list[dict] = []
    for line in trends:
        parts = str(line).split(",")
        if len(parts) < 8:
            continue
        stamp = parts[0].strip()
        close_price = _to_float(parts[2])
        if not stamp or close_price is None:
            continue
        open_price = _to_float(parts[1])
        high_price = _to_float(parts[3])
        low_price = _to_float(parts[4])
        if open_price is None or open_price <= 0:
            open_price = close_price
        if high_price is None or high_price <= 0:
            high_price = close_price
        if low_price is None or low_price <= 0:
            low_price = close_price
        rows.append(
            {
                "time": f"{stamp}:00",
                "open": round(open_price, 4),
                "close": round(close_price, 4),
                "high": round(high_price, 4),
                "low": round(low_price, 4),
                "volume": _to_int(parts[5]) or 0,
                "amount": _to_float(parts[6]),
                "avg": round(_to_float(parts[7]) or close_price, 4),
            }
        )
    if not rows:
        raise MarketDataError("东方财富未返回有效的分时行情")

    raw_name = _clean_text(data.get("name"), 120)
    return {
        "name": raw_name or display_name(symbol),
        "pre_close": _to_float(data.get("preClose")),
        "rows": rows,
    }


def _eastmoney_ticks(symbol: str) -> tuple[float | None, list[dict]]:
    """东方财富逐笔成交：返回最新交易日的秒级明细（已剔除集合竞价与盘后）。"""
    response = _HTTP.get(
        "https://push2.eastmoney.com/api/qt/stock/details/get",
        params={
            "secid": _eastmoney_secid(symbol),
            "fields1": "f1,f2,f3,f4",
            "fields2": "f51,f52,f53,f54,f55",
            "pos": "-100000",
        },
    )
    response.raise_for_status()
    data = (response.json() or {}).get("data") or {}
    details = data.get("details") or []
    pre_close = _to_float(data.get("prePrice"))

    directions = {1: "buy", 2: "sell"}
    if _is_hk_symbol(symbol):
        morning_end, afternoon_end = "12:00:00", "16:00:00"
    else:
        morning_end, afternoon_end = "11:30:00", "15:00:00"
    ticks: list[dict] = []
    for line in details:
        parts = str(line).split(",")
        if len(parts) < 5:
            continue
        stamp = parts[0].strip()
        if not (
            ("09:30:00" <= stamp <= morning_end)
            or ("13:00:00" <= stamp <= afternoon_end)
        ):
            continue
        price = _to_float(parts[1])
        if price is None:
            continue
        volume = _to_int(parts[2]) or 0
        trades = _to_int(parts[3]) or 0
        direction = directions.get(_to_int(parts[4]) or 0, "neutral")
        ticks.append(
            {
                "time": stamp,
                "price": round(price, 4),
                "volume": volume,
                "trades": trades,
                "direction": direction,
            }
        )
    return pre_close, ticks


def _eastmoney_news(symbol: str) -> list[dict]:
    item = lookup(symbol)
    code = _cn_code(symbol)
    keyword = item["cn"] if item and item.get("cn") else code
    param = {
        "uid": "",
        "keyword": keyword,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "time",
                "pageIndex": 1,
                "pageSize": 12,
                "preTag": "",
                "postTag": "",
                "keyword": keyword,
            }
        },
    }
    response = _HTTP.get(
        "https://search-api-web.eastmoney.com/search/jsonp",
        params={"cb": "jsonp", "param": json.dumps(param, ensure_ascii=False)},
    )
    response.raise_for_status()
    text = response.text.strip()
    match = re.match(r"^\s*[\w$]+\((.*)\)\s*;?\s*$", text, re.S)
    payload = json.loads(match.group(1) if match else text)
    articles = ((payload.get("result") or {}).get("cmsArticleWebOld")) or []

    items: list[dict] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = _clean_text(article.get("title"), 300)
        if not title:
            continue
        published = _parse_datetime(article.get("date"))
        if not _news_is_recent(published):
            continue
        items.append(
            {
                "title": title,
                "summary": _clean_text(article.get("content"), 700),
                "url": article.get("url") or "",
                "publisher": _clean_text(article.get("mediaName"), 100) or "东方财富",
                "published_at": published.isoformat() if published else None,
                "thumbnail": article.get("image") or "",
                "symbol": symbol,
                "source": "东方财富",
            }
        )
    return _dedupe_news(items)


def _eastmoney_announcements(symbol: str) -> list[dict]:
    code = _cn_code(symbol)
    response = _HTTP.get(
        "https://np-anotice-stock.eastmoney.com/api/security/ann",
        params={
            "sr": -1,
            "page_size": 10,
            "page_index": 1,
            "ann_type": "A",
            "client_source": "web",
            "stock_list": code,
        },
    )
    response.raise_for_status()
    data = (response.json() or {}).get("data") or {}
    items: list[dict] = []
    for notice in data.get("list") or []:
        if not isinstance(notice, dict):
            continue
        title = _clean_text(notice.get("title"), 300)
        if not title:
            continue
        published = _parse_datetime(notice.get("notice_date") or notice.get("display_time"))
        if not _news_is_recent(published):
            continue
        art_code = str(notice.get("art_code") or "")
        url = (
            f"https://data.eastmoney.com/notices/detail/{code}/{art_code}.html"
            if art_code
            else ""
        )
        items.append(
            {
                "title": title,
                "summary": "",
                "url": url,
                "publisher": "东方财富公告",
                "published_at": published.isoformat() if published else None,
                "thumbnail": "",
                "symbol": symbol,
                "source": "东方财富公告",
            }
        )
    return _dedupe_news(items)


# ---------------------------------------------------------------------------
# Sina / Tencent fallback (used when the primary source is unreachable)
# ---------------------------------------------------------------------------


def _sina_history(symbol: str) -> pd.DataFrame:
    base = symbol.upper().replace(".US", "")
    if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,9}", base):
        raise MarketDataError("新浪回退仅支持美股代码")
    url = (
        "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/"
        f"var%20_{url_quote(base)}=/US_MinKService.getDailyK"
        f"?symbol={url_quote(base)}&___qn=3"
    )
    response = _HTTP.get(url, headers={"Referer": "https://finance.sina.com.cn"})
    response.raise_for_status()
    text = response.content.decode("utf-8", errors="ignore")
    match = re.search(r"\((\[.*\])\)", text, re.S)
    if not match:
        raise MarketDataError("新浪历史行情解析失败")
    try:
        raw_rows = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise MarketDataError("新浪历史行情解析失败") from exc

    cutoff = (date.today() - timedelta(days=732)).isoformat()
    rows = []
    for raw in raw_rows:
        day = str(raw.get("d", ""))
        if not day or day < cutoff:
            continue
        item = {
            "Date": day,
            "Open": _to_float(raw.get("o")),
            "High": _to_float(raw.get("h")),
            "Low": _to_float(raw.get("l")),
            "Close": _to_float(raw.get("c")),
            "Volume": _to_float(raw.get("v")) or 0,
        }
        if item["Open"] is None or item["Close"] is None:
            continue
        rows.append(item)
    if not rows:
        raise MarketDataError("新浪未返回最近两年的历史行情")
    frame = pd.DataFrame(rows).set_index("Date")
    frame.index = pd.to_datetime(frame.index)
    return _normalize_history(frame.rename(columns=str.title))


def _tencent_code(symbol: str) -> str:
    upper = symbol.upper()
    if upper in _INDEX_TO_TENCENT:
        return _INDEX_TO_TENCENT[upper]
    if upper.endswith(".HK"):
        return "hk" + upper[:-3].zfill(5)
    if upper.endswith(".SS"):
        return "sh" + upper[:-3]
    if upper.endswith(".SZ"):
        return "sz" + upper[:-3]
    if upper.endswith(".BJ"):
        return "bj" + upper[:-3]
    base = upper.replace(".US", "")
    return "us" + base.replace("-", ".")


def _tencent_quote_time(symbol: str, raw: Any) -> str:
    text = str(raw or "").strip()
    if re.fullmatch(r"\d{14}", text):
        if _is_cn_symbol(symbol):
            zone = _CN_ZONE
        elif _is_hk_symbol(symbol):
            zone = _HK_ZONE
        else:
            zone = _US_ZONE
        try:
            return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=zone).isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat()


def _tencent_quote(symbol: str) -> dict:
    code = _tencent_code(symbol)
    response = _HTTP.get(f"https://qt.gtimg.cn/q={url_quote(code)}")
    response.raise_for_status()
    text = response.content.decode("gbk", errors="replace")
    if "v_pv_none_match" in text or '="' not in text:
        raise MarketDataError("腾讯行情未返回该代码")
    payload = text.split('="', 1)[1].rsplit('"', 1)[0]
    parts = payload.split("~")
    if len(parts) < 40:
        raise MarketDataError("腾讯行情字段不完整")

    price = _to_float(parts[3])
    previous_close = _to_float(parts[4])
    if price is None:
        raise MarketDataError("腾讯行情未返回最新价")
    if previous_close is None:
        previous_close = price
    change = _to_float(parts[31])
    if change is None:
        change = price - previous_close
    change_pct = _to_float(parts[32])
    if change_pct is None:
        change_pct = (change / previous_close * 100) if previous_close else 0.0

    item = lookup(symbol)
    name = _clean_text(parts[1], 120) if parts[1] else ""
    if not name:
        name = item["name"] if item else display_name(symbol)

    if _is_cn_symbol(symbol):
        market_cap = _to_float(parts[45]) * 100_000_000 if len(parts) > 45 and parts[45] else None
        pe = _to_float(parts[39]) if len(parts) > 39 and parts[39] else None
        high_52w = None
        low_52w = None
        currency = "CNY"
        exchange = _cn_exchange(symbol)
    else:
        market_cap = _to_float(parts[45]) * 100_000_000 if len(parts) > 45 and parts[45] else None
        pe = _to_float(parts[39]) if len(parts) > 39 and parts[39] else None
        high_52w = _to_float(parts[48]) if len(parts) > 48 and parts[48] else None
        low_52w = _to_float(parts[49]) if len(parts) > 49 and parts[49] else None
        currency = parts[35] if len(parts) > 35 and parts[35] else _default_currency(symbol)
        exchange_suffix = parts[2].split(".")[-1] if "." in parts[2] else ""
        exchange_map = {"OQ": "NASDAQ", "N": "NYSE", "AM": "NYSE American", "PK": "OTC"}
        if code.startswith("hk"):
            exchange = "HKEX"
        else:
            exchange = exchange_map.get(exchange_suffix, exchange_suffix or "US")

    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 4),
        "previous_close": round(previous_close, 4),
        "open": round(float(_to_float(parts[5]) or price), 4),
        "day_high": round(float(_to_float(parts[33]) or price), 4),
        "day_low": round(float(_to_float(parts[34]) or price), 4),
        "volume": _to_int(parts[6]),
        "market_cap": market_cap,
        "pe": pe,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "currency": currency,
        "exchange": exchange,
        "session": _market_session(symbol),
        "quote_time": _tencent_quote_time(symbol, parts[30] if len(parts) > 30 else None),
        "quote_timezone": _quote_timezone(symbol),
        "source": "腾讯财经",
    }


# ---------------------------------------------------------------------------
# Yahoo Finance RSS fallback for news
# ---------------------------------------------------------------------------


def _rss_news(symbol: str) -> list[dict]:
    encoded = url_quote(symbol, safe="")
    url = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={encoded}&region=US&lang=en-US"
    )
    response = _HTTP.get(url)
    response.raise_for_status()
    text = response.content.decode("utf-8", errors="ignore")
    if "<rss" not in text.lower():
        raise MarketDataError("Yahoo 新闻 RSS 暂不可用")
    root = ET.fromstring(text)
    items: list[dict] = []
    for node in root.iter("item"):
        title = _clean_text(node.findtext("title"), 300)
        if not title:
            continue
        summary = _clean_text(node.findtext("description"), 700)
        link = (node.findtext("link") or "").strip()
        published = _parse_datetime(node.findtext("pubDate"))
        if not _news_is_recent(published):
            continue
        source_node = node.find("source")
        publisher = _clean_text(source_node.text, 100) if source_node is not None else ""
        if not publisher:
            publisher = _publisher_from_url(link)
        items.append(
            {
                "title": title,
                "summary": summary,
                "url": link,
                "publisher": publisher,
                "published_at": published.isoformat() if published else None,
                "thumbnail": "",
                "symbol": symbol,
                "source": "Yahoo Finance RSS",
            }
        )
    return _dedupe_news(items)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _get_quote(symbol: str, refresh: bool = False) -> dict:
    key = f"quote:{symbol}"
    if not refresh:
        cached = _cache.get(key)
        if cached is not None:
            return cached

    if _is_cn_symbol(symbol):
        try:
            quote = _eastmoney_quote(symbol)
        except Exception as exc:
            try:
                quote = _tencent_quote(symbol)
            except Exception as fallback_exc:
                raise MarketDataError(
                    f"东方财富与腾讯行情均不可用: {fallback_exc}"
                ) from exc
        _cache.set(key, quote, 25.0)
        return quote

    if _is_hk_symbol(symbol):
        errors: list[str] = []
        try:
            quote = _eastmoney_quote(symbol)
            _cache.set(key, quote, 25.0)
            return quote
        except Exception as exc:
            errors.append(f"东方财富: {exc}")
        try:
            quote = _tencent_quote(symbol)
            _cache.set(key, quote, 25.0)
            return quote
        except Exception as exc:
            errors.append(f"腾讯: {exc}")
        if _yf_allowed():
            try:
                quote = _call_with_timeout(lambda: _yf_quote(symbol), 9.0)
                _yf_circuit.success()
                _cache.set(key, quote, 25.0)
                return quote
            except Exception as exc:
                errors.append(f"Yahoo: {exc}")
        raise MarketDataError("港股行情暂不可用（" + "；".join(errors) + "）")

    quote = None
    yf_error: Exception | None = None
    if _yf_allowed():
        try:
            quote = _call_with_timeout(lambda: _yf_quote(symbol), 9.0)
            _yf_circuit.success()
        except Exception as exc:
            yf_error = exc
            _yf_circuit.open_for(300.0)
            _cache.set("yf:reachable", False, 180.0)
            logger.info("yfinance quote failed for %s: %s", symbol, exc)

    if quote is None:
        try:
            quote = _tencent_quote(symbol)
        except Exception as exc:
            if yf_error is not None:
                raise MarketDataError(f"Yahoo 与腾讯行情均不可用: {exc}") from exc
            raise

    _cache.set(key, quote, 25.0)
    return quote


def get_quotes(symbols: list[str], refresh: bool = False) -> dict:
    normalized: list[str] = []
    for raw in symbols:
        symbol = normalize_symbol(raw)
        if is_valid_symbol(symbol) and symbol not in normalized:
            normalized.append(symbol)

    results: list[dict] = []
    errors: list[dict] = []
    if not normalized:
        return {"quotes": results, "errors": errors}

    with ThreadPoolExecutor(max_workers=min(6, len(normalized))) as executor:
        futures = {
            executor.submit(_get_quote, symbol, refresh): symbol
            for symbol in normalized
        }
        by_symbol: dict[str, dict] = {}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                by_symbol[symbol] = future.result()
            except Exception as exc:
                errors.append({"symbol": symbol, "message": str(exc)})
        for symbol in normalized:
            if symbol in by_symbol:
                quote = by_symbol[symbol]
                quote.setdefault("lot_size", lot_size(symbol))
                results.append(quote)

    return {"quotes": results, "errors": errors}


def get_history_frame(symbol: str, refresh: bool = False) -> pd.DataFrame:
    """Return a cached daily history frame without pulling news.

    Used by the simulated-trading account summary to look up month-start prices.
    """
    symbol = normalize_symbol(symbol)
    if not is_valid_symbol(symbol):
        raise MarketDataError(f"无效代码: {symbol}")

    key = f"history:{symbol}"
    if not refresh:
        cached = _cache.get(key)
        if cached is not None:
            return cached

    history: pd.DataFrame | None = None
    if _is_cn_symbol(symbol) or _is_hk_symbol(symbol):
        try:
            history = _eastmoney_history(symbol)
        except Exception as exc:
            logger.info("eastmoney history (trading) failed for %s: %s", symbol, exc)
        if history is None and _yf_allowed():
            try:
                history, _ = _call_with_timeout(
                    lambda: _yf_history_and_quote(symbol), 16.0
                )
                _yf_circuit.success()
            except Exception as exc:
                _yf_circuit.open_for(300.0)
                _cache.set("yf:reachable", False, 180.0)
                logger.info("yfinance history (trading) failed for %s: %s", symbol, exc)
    else:
        if _yf_allowed():
            try:
                history, _ = _call_with_timeout(
                    lambda: _yf_history_and_quote(symbol), 16.0
                )
                _yf_circuit.success()
            except Exception as exc:
                _yf_circuit.open_for(300.0)
                _cache.set("yf:reachable", False, 180.0)
                logger.info("yfinance history (trading) failed for %s: %s", symbol, exc)
        if history is None:
            history = _sina_history(symbol)

    if history is None or history.empty:
        raise MarketDataError(f"{symbol} 的历史行情暂不可用")
    _cache.set(key, history, 300.0)
    return history


def get_intraday(symbol: str, range_key: str = "DAY", refresh: bool = False) -> dict:
    """Return intraday time series for an A-share or HK symbol.

    DAY: tick-by-tick trades for the latest trading day (second precision).
    WEEK: 1-minute OHLC for the current week (timestamps carry :00 seconds).
    """
    symbol = normalize_symbol(symbol)
    if not is_valid_symbol(symbol):
        raise MarketDataError(f"无效代码: {symbol}")
    if not (_is_cn_symbol(symbol) or _is_hk_symbol(symbol)):
        raise MarketDataError("分时数据目前仅支持 A 股与港股标的")

    range_key = "WEEK" if str(range_key).upper() == "WEEK" else "DAY"
    key = f"intraday:{symbol}:{range_key}"
    if not refresh:
        cached = _cache.get(key)
        if cached is not None:
            return cached

    trends = _eastmoney_trends(symbol)
    rows = trends["rows"]
    latest_date = rows[-1]["time"][:10]
    pre_close = trends.get("pre_close")

    if range_key == "DAY":
        day_rows = [row for row in rows if row["time"][:10] == latest_date]
        tick_pre_close, ticks = (None, [])
        try:
            tick_pre_close, ticks = _eastmoney_ticks(symbol)
        except Exception as exc:
            logger.info("eastmoney ticks failed for %s: %s", symbol, exc)
        if ticks:
            points = [
                {
                    "time": f"{latest_date} {tick['time']}",
                    "price": tick["price"],
                    "volume": tick["volume"],
                    "direction": tick["direction"],
                }
                for tick in ticks
            ]
            granularity = "tick"
            if tick_pre_close:
                pre_close = tick_pre_close
        else:
            points = [
                {
                    "time": row["time"],
                    "price": row["close"],
                    "volume": row["volume"],
                    "direction": None,
                }
                for row in day_rows
            ]
            granularity = "minute"
        candles = day_rows
    else:
        latest = date.fromisoformat(latest_date)
        monday = latest - timedelta(days=latest.weekday())
        cutoff = monday.isoformat()
        week_rows = [row for row in rows if row["time"][:10] >= cutoff]
        if not week_rows:
            raise MarketDataError("东方财富未返回本周分时数据")
        points = [
            {
                "time": row["time"],
                "price": row["close"],
                "volume": row["volume"],
                "direction": None,
            }
            for row in week_rows
        ]
        candles = week_rows
        granularity = "minute"

    if not points:
        raise MarketDataError("东方财富未返回分时数据")

    result = {
        "symbol": symbol,
        "name": trends.get("name") or display_name(symbol),
        "range": range_key,
        "granularity": granularity,
        "pre_close": round(pre_close, 4) if pre_close else None,
        "as_of": points[-1]["time"],
        "source": "东方财富",
        "points": points,
        "candles": candles,
    }
    ttl = 3.0 if range_key == "DAY" and granularity == "tick" else 10.0
    _cache.set(key, result, ttl)
    return result


def _load_news(symbol: str, yf_available: bool, refresh: bool = False) -> tuple[list[dict], list[str]]:
    key = f"news:{symbol}"
    if not refresh:
        cached = _cache.get(key)
        if cached is not None:
            return cached

    warnings: list[str] = []
    items: list[dict] = []
    if _is_cn_symbol(symbol) or _is_hk_symbol(symbol):
        try:
            items.extend(_eastmoney_news(symbol))
        except Exception as exc:
            warnings.append(f"{symbol} 的东方财富新闻接口未返回数据")
            logger.info("eastmoney news failed for %s: %s", symbol, exc)
        # 公告接口按 A 股代码索引，港股不适用。
        if not items and _is_cn_symbol(symbol):
            try:
                items.extend(_eastmoney_announcements(symbol))
            except Exception as exc:
                warnings.append(f"{symbol} 的东方财富公告接口暂不可用")
                logger.info("eastmoney announcements failed for %s: %s", symbol, exc)
        if not items and _is_hk_symbol(symbol) and yf_available and _yf_allowed():
            try:
                items.extend(_call_with_timeout(lambda: _yf_news(symbol), 9.0))
            except Exception as exc:
                logger.info("yfinance news failed for HK %s: %s", symbol, exc)
    else:
        if yf_available and _yf_allowed():
            try:
                items.extend(_call_with_timeout(lambda: _yf_news(symbol), 9.0))
            except Exception as exc:
                warnings.append(f"{symbol} 的 Yahoo 新闻接口未返回数据")
                logger.info("yfinance news failed for %s: %s", symbol, exc)

        try:
            items.extend(_rss_news(symbol))
        except Exception as exc:
            warnings.append(f"{symbol} 的 Yahoo RSS 新闻暂不可用")
            logger.info("Yahoo RSS news failed for %s: %s", symbol, exc)

    merged = _dedupe_news(items)[:16]
    result = (merged, warnings)
    _cache.set(key, result, 300.0)
    return result


def get_bundle(symbol: str, refresh: bool = False) -> dict:
    symbol = normalize_symbol(symbol)
    if not is_valid_symbol(symbol):
        raise MarketDataError(f"无效代码: {symbol}")

    key = f"bundle:{symbol}"
    if not refresh:
        cached = _cache.get(key)
        if cached is not None:
            return cached

    with _bundle_lock(symbol):
        if not refresh:
            cached = _cache.get(key)
            if cached is not None:
                return cached

        history: pd.DataFrame | None = None
        quote: dict | None = None
        provider = ""
        warnings: list[str] = []
        yf_available = False

        if _is_cn_symbol(symbol) or _is_hk_symbol(symbol):
            try:
                history = _eastmoney_history(symbol)
                provider = "东方财富"
            except Exception as exc:
                logger.info("eastmoney history failed for %s: %s", symbol, exc)
                warnings.append(f"{symbol} 的东方财富历史行情不可用，已尝试备用数据源")

            if quote is None:
                try:
                    quote = _eastmoney_quote(symbol)
                except Exception as exc:
                    logger.info("eastmoney quote failed for %s: %s", symbol, exc)
                    try:
                        quote = _tencent_quote(symbol)
                    except Exception as fallback_exc:
                        logger.info(
                            "tencent quote failed for %s: %s", symbol, fallback_exc
                        )

            if history is None and _yf_allowed():
                try:
                    history, quote = _call_with_timeout(
                        lambda: _yf_history_and_quote(symbol), 16.0
                    )
                    provider = "Yahoo Finance"
                    yf_available = True
                    _yf_circuit.success()
                except Exception as exc:
                    _yf_circuit.open_for(300.0)
                    _cache.set("yf:reachable", False, 180.0)
                    logger.info("yfinance history failed for %s: %s", symbol, exc)

            if history is None:
                market_name = "港股" if _is_hk_symbol(symbol) else "A 股"
                raise MarketDataError(f"{symbol} 的{market_name}历史行情暂不可用")
        else:
            if _yf_allowed():
                try:
                    history, quote = _call_with_timeout(
                        lambda: _yf_history_and_quote(symbol), 16.0
                    )
                    provider = "Yahoo Finance"
                    yf_available = True
                    _yf_circuit.success()
                except Exception as exc:
                    _yf_circuit.open_for(300.0)
                    _cache.set("yf:reachable", False, 180.0)
                    logger.info("yfinance history failed for %s: %s", symbol, exc)
                    warnings.append(f"{symbol} 的 Yahoo 行情不可用，已尝试备用数据源")

            if history is None:
                if symbol.startswith("^") or symbol.endswith(".HK"):
                    raise MarketDataError(
                        f"{symbol} 的 Yahoo 历史行情不可用，当前备用源仅支持美股"
                    )
                history = _sina_history(symbol)
                try:
                    quote = _tencent_quote(symbol)
                except Exception:
                    quote = _quote_from_history(
                        symbol,
                        history,
                        name=display_name(symbol),
                        source="Sina Finance",
                        currency="USD",
                        exchange="US",
                    )
                provider = "Sina Finance"
                yf_available = False

        if quote is None:
            quote = _quote_from_history(
                symbol,
                history,
                name=display_name(symbol),
                source=provider,
                currency=_default_currency(symbol),
                exchange=_exchange_label(symbol) or None,
            )

        news, news_warnings = _load_news(symbol, yf_available=yf_available, refresh=refresh)
        warnings.extend(news_warnings)
        if not news:
            warnings.append(f"{symbol} 最近 30 天暂无可用的新闻条目")

        item = lookup(symbol)
        name = quote.get("name") or (item["name"] if item else display_name(symbol))
        quote["name"] = name
        quote.setdefault("lot_size", lot_size(symbol))

        bundle = {
            "symbol": symbol,
            "name": name,
            "quote": quote,
            "history": history,
            "news": news,
            "provider": provider,
            "warnings": warnings,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        _cache.set(key, bundle, 300.0)
        return bundle


def clear_symbol_cache(symbols: list[str]) -> None:
    for raw in symbols:
        symbol = normalize_symbol(raw)
        _cache.delete(f"bundle:{symbol}")
        _cache.delete(f"quote:{symbol}")
        _cache.delete(f"news:{symbol}")
        _cache.delete(f"history:{symbol}")


def provider_health() -> dict:
    return {
        "yfinance_circuit": _yf_circuit.snapshot(),
        "fallback": "东方财富 + 腾讯财经 + Yahoo Finance",
    }
