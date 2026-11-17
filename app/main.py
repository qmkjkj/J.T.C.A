from __future__ import annotations

import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import ai_watch, auth, database, providers
from .admin_routes import router as admin_router
from .auth_routes import router as auth_router
from .trading_routes import router as trading_router
from .analytics import (
    average_pairwise_correlation,
    build_series,
    compute_metrics,
    correlation_matrix,
)
from .cache import TTLCache
from .config import (
    ADMIN_PATH,
    ADMIN_UI_DIR,
    APP_NAME,
    APP_SUBTITLE,
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEFAULT_SELECTED,
    DEFAULT_WATCHLIST,
    DISCLAIMER,
    MARKET_SYMBOLS,
    MAX_SELECTION,
    PLATFORMS,
    STATIC_DIR,
    platform_meta,
)
from .deepseek import (
    AnalysisError,
    analyze_portfolio,
    optimize_allocation,
    screen_candidates,
)
from .universe import (
    HK_UNIVERSE,
    UNIVERSE,
    is_valid_symbol,
    normalize_symbol,
    platform_of_symbols,
    search as search_universe,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await run_in_threadpool(database.ensure_schema)
        logger.info("account database ready")
    except Exception as exc:
        logger.warning("account database unavailable at startup: %s", exc)
    if DEEPSEEK_API_KEY and database.is_configured():
        ai_watch.worker.start()
    try:
        yield
    finally:
        ai_watch.worker.stop()


app = FastAPI(
    title="J.T.C.A / J.T.C.G 量化分析工具",
    description="A 股与港股行情、新闻与 AI 研判分析",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1200)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(trading_router)

_PUBLIC_PATHS = {"/login", ADMIN_PATH, "/favicon.svg", "/api/health"}
_PUBLIC_PREFIXES = ("/static/", "/api/auth/", "/api/admin/", ADMIN_PATH + "/")


def _is_public_path(path: str) -> bool:
    return path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or _is_public_path(path):
        return await call_next(request)
    try:
        session = await run_in_threadpool(auth.user_session_from_request, request)
    except database.DatabaseUnavailable:
        return JSONResponse(
            status_code=503, content={"detail": "数据库暂不可用，请稍后重试"}
        )
    except Exception:
        logger.exception("auth guard failed")
        return JSONResponse(
            status_code=503, content={"detail": "账号服务暂不可用，请稍后重试"}
        )
    if session:
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "请先登录"})
    target = path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(
        url=f"/login?next={quote(target, safe='')}", status_code=307
    )


_analysis_cache = TTLCache()
_SYMBOL_SPLIT = re.compile(r"[,\s]+")


def _is_a_share(symbol: str) -> bool:
    return symbol.upper().endswith((".SS", ".SZ", ".BJ"))


def _is_hk(symbol: str) -> bool:
    upper = symbol.upper()
    return upper.endswith(".HK") or upper in {"^HSI", "^HSCE", "^HSTECH"}


def _primary_provider(symbol: str) -> str:
    return "东方财富" if (_is_a_share(symbol) or _is_hk(symbol)) else "Yahoo Finance"


def _resolve_platform(value: str | None, symbols: list[str] | None = None) -> str:
    key = (value or "").strip().upper()
    if key in PLATFORMS:
        return key
    if symbols:
        return platform_of_symbols(symbols)
    return "CN"


class AnalysisRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    refresh: bool = False
    force: bool = False
    platform: str | None = None


class ScreenRequest(BaseModel):
    capital: float = Field(ge=200, le=1_000_000_000)
    count: int = Field(default=8, ge=3, le=12)
    platform: str | None = None


class OptimizeRequest(BaseModel):
    capital: float = Field(ge=200, le=1_000_000_000)
    candidates: list[str] = Field(default_factory=list)
    platform: str | None = None


class WatchRequest(BaseModel):
    strategy: int = Field(default=50, ge=0, le=100)
    refresh: bool = False


class WatchSettingsRequest(BaseModel):
    enabled: bool = False
    strategy: int = Field(default=50, ge=0, le=100)


def _parse_symbols(raw: str | None, max_count: int = MAX_SELECTION) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for token in _SYMBOL_SPLIT.split(raw):
        symbol = normalize_symbol(token)
        if not symbol:
            continue
        if not is_valid_symbol(symbol):
            raise HTTPException(status_code=422, detail=f"无效代码: {token}")
        if symbol not in out:
            out.append(symbol)
    if len(out) > max_count:
        raise HTTPException(
            status_code=422,
            detail=f"最多同时处理 {max_count} 个标的",
        )
    return out


def _clean_symbols(values: list[str], max_count: int = MAX_SELECTION) -> list[str]:
    out: list[str] = []
    for raw in values:
        symbol = normalize_symbol(raw)
        if not symbol:
            continue
        if not is_valid_symbol(symbol):
            raise HTTPException(status_code=422, detail=f"无效代码: {raw}")
        if symbol not in out:
            out.append(symbol)
    if len(out) > max_count:
        raise HTTPException(
            status_code=422,
            detail=f"最多同时处理 {max_count} 个标的",
        )
    return out


def _serialize_bundle(bundle: dict) -> dict:
    history = bundle["history"]
    series = build_series(history)
    metrics = compute_metrics(history, bundle["quote"])
    return {
        "symbol": bundle["symbol"],
        "name": bundle["name"],
        "quote": bundle["quote"],
        "provider": bundle["provider"],
        "history": series,
        "metrics": metrics,
        "news": bundle.get("news", []),
        "warnings": bundle.get("warnings", []),
    }


def _build_portfolio(symbols: list[str], refresh: bool = False) -> dict:
    if not symbols:
        raise HTTPException(status_code=422, detail="请至少选择一个标的")
    if refresh:
        providers.clear_symbol_cache(symbols)

    bundles: list[dict] = []
    errors: list[dict] = []
    warnings: list[str] = []

    with ThreadPoolExecutor(max_workers=min(4, len(symbols))) as executor:
        futures = {
            executor.submit(providers.get_bundle, symbol, refresh): symbol
            for symbol in symbols
        }
        found: dict[str, dict] = {}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                found[symbol] = future.result()
            except Exception as exc:
                logger.warning("bundle failed for %s: %s", symbol, exc)
                errors.append({"symbol": symbol, "message": str(exc)})
    for symbol in symbols:
        if symbol in found:
            bundles.append(found[symbol])

    if not bundles:
        details = "; ".join(f"{item['symbol']}: {item['message']}" for item in errors)
        raise HTTPException(
            status_code=502,
            detail=f"未能获取所选标的的行情数据。{details or '请稍后重试'}",
        )

    serialized = [_serialize_bundle(bundle) for bundle in bundles]
    for item in serialized:
        warnings.extend(item.get("warnings", []))
    warnings = list(dict.fromkeys(warnings))

    feed_map: dict[str, dict] = {}
    for item in serialized:
        for news in item.get("news", []):
            key = news.get("url") or news.get("title", "").lower()
            if not key:
                continue
            existing = feed_map.get(key)
            if existing is None:
                feed_map[key] = {**news, "symbols": [item["symbol"]]}
            elif item["symbol"] not in existing["symbols"]:
                existing["symbols"].append(item["symbol"])
    feed = list(feed_map.values())
    feed.sort(key=lambda news: news.get("published_at") or "", reverse=True)

    corr = correlation_matrix(bundles)
    avg_corr = average_pairwise_correlation(corr)
    providers_used = sorted({item["provider"] for item in serialized})
    fallback_used = any(
        item["provider"] != _primary_provider(item["symbol"]) for item in serialized
    )
    if fallback_used:
        warnings.append(
            "部分标的的主行情源当前不可用，已自动切换到备用行情源。"
        )

    snapshot_at = datetime.now(timezone.utc).isoformat()
    return {
        "snapshot_at": snapshot_at,
        "symbols": serialized,
        "news_feed": feed,
        "correlation": corr,
        "average_correlation": avg_corr,
        "providers": providers_used,
        "errors": errors,
        "warnings": warnings,
        "liquidity_note": (
            "部分标的使用了备用行情源，数据口径可能与主行情源略有差异。"
            if fallback_used
            else "全部标的均使用主行情源数据。"
        ),
        "news_count": sum(len(item.get("news", [])) for item in serialized),
    }


def _analysis_cache_key(portfolio: dict) -> str:
    compact = {
        "model": DEEPSEEK_MODEL,
        "symbols": [
            {
                "symbol": item["symbol"],
                "price": item["quote"].get("price"),
                "quote_time": item["quote"].get("quote_time"),
                "latest": item["metrics"].get("as_of"),
                "news": [news.get("title") for news in item.get("news", [])],
                "rsi": item["metrics"].get("rsi14"),
            }
            for item in portfolio.get("symbols", [])
        ],
    }
    digest = hashlib.sha256(
        json.dumps(compact, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"analysis:{digest}"


@app.get("/api/config")
def api_config(platform: str = Query(default="CN", max_length=8)) -> dict:
    key = _resolve_platform(platform)
    meta = platform_meta(key)
    return {
        "platform": key,
        "platforms": [
            {
                "code": code,
                "app_name": item["app_name"],
                "subtitle": item["subtitle"],
                "market_label": item["market_label"],
                "market_short": item["market_short"],
            }
            for code, item in PLATFORMS.items()
        ],
        "app_name": meta["app_name"],
        "subtitle": meta["subtitle"],
        "model": meta["model"],
        "market_label": meta["market_label"],
        "market_short": meta["market_short"],
        "currency": meta["currency"],
        "currency_symbol": meta["currency_symbol"],
        "currency_name": meta["currency_name"],
        "session_note": meta["session_note"],
        "lot_note": meta["lot_note"],
        "rule_note": meta["rule_note"],
        "ai_configured": bool(DEEPSEEK_API_KEY),
        "max_selection": MAX_SELECTION,
        "default_watchlist": meta["default_watchlist"],
        "default_selected": DEFAULT_SELECTED,
        "market_symbols": meta["market_symbols"],
        "disclaimer": meta["disclaimer"],
        "providers": meta["providers"],
        "universe_size": len(HK_UNIVERSE if key == "HK" else UNIVERSE),
    }


@app.get("/api/health")
def api_health() -> dict:
    return {
        "status": "ok",
        "app": APP_NAME,
        "model": "J.T.C.A AI",
        "ai_configured": bool(DEEPSEEK_API_KEY),
        **providers.provider_health(),
    }


@app.get("/api/search")
def api_search(
    q: str = Query(default="", max_length=80),
    platform: str = Query(default="CN", max_length=8),
) -> dict:
    key = _resolve_platform(platform)
    results = search_universe(q, limit=8, platform=key)
    query = q.strip().upper()
    normalized_query = normalize_symbol(query)
    has_exact = any(item["symbol"].upper() == normalized_query for item in results)
    custom_platform = key
    if query and is_valid_symbol(query) and not has_exact:
        results.append(
            {
                "symbol": normalized_query,
                "name": query,
                "cn": "",
                "exchange": "",
                "region": custom_platform,
                "kind": "自定义代码",
                "custom": True,
            }
        )
    return {"query": q, "platform": key, "results": results[:9]}


@app.get("/api/quotes")
def api_quotes(
    symbols: str = Query(default="", max_length=240),
    refresh: bool = Query(default=False),
) -> dict:
    parsed = _parse_symbols(symbols, max_count=12)
    if not parsed:
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "quotes": [],
            "errors": [],
        }
    result = providers.get_quotes(parsed, refresh=refresh)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        **result,
    }


@app.get("/api/market")
def api_market(
    refresh: bool = Query(default=False),
    platform: str = Query(default="CN", max_length=8),
) -> dict:
    key = _resolve_platform(platform)
    meta = platform_meta(key)
    result = providers.get_quotes(meta["market_symbols"], refresh=refresh)
    return {
        "platform": key,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "quotes": result["quotes"],
        "errors": result["errors"],
    }


@app.get("/api/intraday")
def api_intraday(
    symbol: str = Query(default="", max_length=40),
    range: str = Query(default="DAY", max_length=10),
    refresh: bool = Query(default=False),
) -> dict:
    normalized = normalize_symbol(symbol)
    if not normalized or not is_valid_symbol(normalized):
        raise HTTPException(status_code=422, detail=f"无效代码: {symbol}")
    try:
        return providers.get_intraday(normalized, range, refresh=refresh)
    except providers.MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("intraday failed for %s: %s", normalized, exc)
        raise HTTPException(
            status_code=502, detail="分时数据暂不可用，请稍后重试"
        ) from exc


@app.get("/api/portfolio")
def api_portfolio(
    symbols: str = Query(default="", max_length=240),
    refresh: bool = Query(default=False),
) -> dict:
    parsed = _parse_symbols(symbols, max_count=MAX_SELECTION)
    return _build_portfolio(parsed, refresh=refresh)


@app.post("/api/analysis")
async def api_analysis(request: AnalysisRequest) -> dict:
    symbols = _clean_symbols(request.symbols, max_count=MAX_SELECTION)
    if not symbols:
        raise HTTPException(status_code=422, detail="请至少选择一个标的")
    if not DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="智能分析服务暂不可用，请稍后重试",
        )

    portfolio = await run_in_threadpool(_build_portfolio, symbols, request.refresh)
    cache_key = _analysis_cache_key(portfolio)
    if not request.refresh and not request.force:
        cached = _analysis_cache.get(cache_key)
        if cached is not None:
            return {**cached, "cached": True}

    market = _resolve_platform(request.platform, symbols)
    try:
        analysis = await analyze_portfolio(portfolio, market=market)
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("analysis failed")
        raise HTTPException(status_code=500, detail=f"分析失败: {exc}") from exc

    payload = {
        "analysis": analysis,
        "meta": analysis.get("meta", {}),
        "portfolio_meta": {
            "snapshot_at": portfolio.get("snapshot_at"),
            "data_as_of": max(
                (
                    item["metrics"].get("as_of")
                    for item in portfolio.get("symbols", [])
                    if item["metrics"].get("as_of")
                ),
                default=None,
            ),
            "news_count": portfolio.get("news_count"),
            "providers": portfolio.get("providers"),
            "average_correlation": portfolio.get("average_correlation"),
        },
        "cached": False,
    }
    _analysis_cache.set(cache_key, payload, 900.0)
    return payload


@app.get("/api/account/ai-watch")
def api_ai_watch_status(user: dict = Depends(auth.require_user)) -> dict:
    try:
        return ai_watch.status(int(user["user_id"]))
    except database.DatabaseUnavailable as exc:
        logger.warning("ai watch status database error: %s", exc)
        raise HTTPException(
            status_code=503, detail="数据库暂不可用，请稍后重试"
        ) from exc


@app.post("/api/account/ai-watch/settings")
async def api_ai_watch_settings(
    body: WatchSettingsRequest, user: dict = Depends(auth.require_user)
) -> dict:
    """开启 / 关闭 AI 盯盘。开启后立即评估一次，之后由后台进程每 30 分钟自动盯盘并抛售。"""
    user_id = int(user["user_id"])
    if body.enabled and not DEEPSEEK_API_KEY:
        raise HTTPException(status_code=503, detail="智能盯盘服务暂不可用，请稍后重试")

    try:
        settings = await run_in_threadpool(
            ai_watch.save_settings, user_id, body.enabled, body.strategy
        )
    except database.DatabaseUnavailable as exc:
        logger.warning("ai watch settings database error: %s", exc)
        raise HTTPException(
            status_code=503, detail="数据库暂不可用，请稍后重试"
        ) from exc

    result = None
    error = None
    if body.enabled:
        try:
            result = await ai_watch.evaluate_user(
                user_id, body.strategy, refresh=True, execute=True
            )
        except Exception as exc:
            # 开关已经写入数据库，首次评估失败时保留后台重试，不把开关回滚。
            logger.warning("ai watch initial run failed: %s", exc)
            error = str(exc) or "智能盯盘失败，请稍后重试"

    return {
        "settings": settings,
        "status": ai_watch.status(user_id),
        "result": result,
        "error": error,
    }


@app.post("/api/account/ai-watch")
async def api_ai_watch(
    body: WatchRequest, user: dict = Depends(auth.require_user)
) -> dict:
    """手动触发一次盯盘；AI 盯盘已开启时同样会自动抛售。"""
    if not DEEPSEEK_API_KEY:
        raise HTTPException(status_code=503, detail="智能盯盘服务暂不可用，请稍后重试")

    user_id = int(user["user_id"])
    try:
        settings = await run_in_threadpool(ai_watch.get_settings, user_id)
    except database.DatabaseUnavailable as exc:
        logger.warning("ai watch settings database error: %s", exc)
        raise HTTPException(
            status_code=503, detail="数据库暂不可用，请稍后重试"
        ) from exc

    try:
        return await ai_watch.evaluate_user(
            user_id,
            body.strategy,
            refresh=body.refresh,
            execute=bool(settings.get("enabled")),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("ai watch failed")
        raise HTTPException(
            status_code=500, detail="智能盯盘失败，请稍后重试"
        ) from exc


@app.post("/api/screen/candidates")
async def api_screen_candidates(request: ScreenRequest) -> dict:
    if not DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="智能分析服务暂不可用，请稍后重试",
        )
    market = _resolve_platform(request.platform)
    source = HK_UNIVERSE if market == "HK" else UNIVERSE
    symbols = [item["symbol"] for item in source]
    quote_result = await run_in_threadpool(providers.get_quotes, symbols)
    quote_map = {
        quote["symbol"]: quote
        for quote in quote_result.get("quotes", [])
        if quote.get("symbol")
    }
    pool: list[dict] = []
    for item in source:
        quote = quote_map.get(item["symbol"]) or {}
        price = quote.get("price")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        lot = int(item.get("lot_size") or 100)
        pool.append(
            {
                "symbol": item["symbol"],
                "name": item["name"],
                "kind": item["kind"],
                "price": price,
                "lot_size": lot,
                "lot_cost": round(price * lot, 2) if price and price > 0 else None,
            }
        )

    try:
        result = await screen_candidates(request.capital, pool, request.count, market=market)
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("screening failed")
        raise HTTPException(status_code=500, detail=f"自动筛选失败: {exc}") from exc

    return {
        "capital": request.capital,
        "platform": market,
        **result,
        "universe_size": len(pool),
        "quote_errors": len(quote_result.get("errors", [])),
    }


@app.post("/api/screen/optimize")
async def api_screen_optimize(request: Request, body: OptimizeRequest) -> dict:
    if not DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="智能分析服务暂不可用，请稍后重试",
        )
    symbols = _clean_symbols(body.candidates, max_count=12)
    if not symbols:
        raise HTTPException(status_code=422, detail="请提供候选股票代码")

    market = _resolve_platform(body.platform, symbols)
    portfolio = await run_in_threadpool(_build_portfolio, symbols, False)
    try:
        result = await optimize_allocation(
            portfolio, body.capital, MAX_SELECTION, market=market
        )
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("allocation failed")
        raise HTTPException(status_code=500, detail=f"自动配置失败: {exc}") from exc

    result["providers"] = portfolio.get("providers")
    result["warnings"] = portfolio.get("warnings")
    result["platform"] = market
    result["candidates_used"] = [
        item["symbol"] for item in portfolio.get("symbols", [])
    ]
    _log_screen_run(request, body.capital, result)
    return result


def _log_screen_run(request: Request, capital: float, result: dict) -> None:
    try:
        session = auth.user_session_from_request(request)
        user_id = session["user_id"] if session else None
        allocations = [
            {
                key: item.get(key)
                for key in ("symbol", "name", "shares", "amount", "actual_weight")
            }
            for item in result.get("allocations", [])
        ]
        with database.cursor() as cur:
            cur.execute(
                """
                INSERT INTO screen_runs
                    (user_id, capital, candidates, allocations, summary, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (
                    user_id,
                    capital,
                    json.dumps(result.get("candidates_used") or [], ensure_ascii=False)[:20000],
                    json.dumps(allocations, ensure_ascii=False)[:20000],
                    (result.get("summary") or "")[:5000],
                ),
            )
    except Exception:
        logger.warning("failed to log screen run", exc_info=True)


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get(ADMIN_PATH)
def admin_page() -> FileResponse:
    return FileResponse(ADMIN_UI_DIR / "admin.html")


@app.get(ADMIN_PATH + "/admin.js")
def admin_script() -> FileResponse:
    return FileResponse(
        ADMIN_UI_DIR / "admin.js", media_type="application/javascript; charset=utf-8"
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.svg")
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
