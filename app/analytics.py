from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _round(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _pct(value: Any) -> float | None:
    return _round(value, 2)


def _series_to_list(series: pd.Series, digits: int = 4) -> list[float | None]:
    result: list[float | None] = []
    for value in series.tolist():
        result.append(_round(value, digits))
    return result


def _return_over(close: pd.Series, days: int) -> float | None:
    if len(close) <= days:
        return None
    start = float(close.iloc[-days - 1])
    end = float(close.iloc[-1])
    if start == 0:
        return None
    return (end / start - 1.0) * 100.0


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1.0 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1.0 / period, adjust=False).mean()
    last_gain = float(gain.iloc[-1])
    last_loss = float(loss.iloc[-1])
    if last_loss == 0:
        return 100.0 if last_gain > 0 else 50.0
    rs = last_gain / last_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_metrics(history: pd.DataFrame, quote: dict) -> dict:
    close = history["Close"].astype(float)
    high = history["High"].astype(float)
    low = history["Low"].astype(float)
    volume = history["Volume"].astype(float)
    returns = close.pct_change(fill_method=None).dropna()

    last = float(close.iloc[-1])
    sma20 = close.rolling(20, min_periods=20).mean().iloc[-1]
    sma50 = close.rolling(50, min_periods=50).mean().iloc[-1]
    sma200 = close.rolling(200, min_periods=200).mean().iloc[-1]
    high_52w = float(high.tail(252).max())
    low_52w = float(low.tail(252).min())
    range_span = high_52w - low_52w
    range_position = ((last - low_52w) / range_span * 100.0) if range_span > 0 else None

    if len(close) > 252:
        window = close.tail(252)
        max_dd = float((window / window.cummax() - 1.0).min() * 100.0)
    else:
        max_dd = float((close / close.cummax() - 1.0).min() * 100.0)

    vol_30d = None
    if len(returns) >= 20:
        vol_30d = float(returns.tail(30).std(ddof=0) * math.sqrt(252) * 100.0)

    avg_volume_20d = volume.tail(20).mean() if len(volume) >= 1 else None
    last_volume = float(volume.iloc[-1]) if len(volume) else None
    volume_ratio = (
        last_volume / float(avg_volume_20d)
        if avg_volume_20d and float(avg_volume_20d) > 0 and last_volume is not None
        else None
    )

    trend = "震荡"
    if sma20 is not None and sma50 is not None:
        if last > sma20 > sma50:
            trend = "多头排列"
        elif last < sma20 < sma50:
            trend = "空头排列"
        elif last > sma50:
            trend = "中期偏强"
        else:
            trend = "中期偏弱"

    quote_high = quote.get("high_52w")
    quote_low = quote.get("low_52w")
    if quote_high is not None:
        high_52w = max(high_52w, float(quote_high))
    if quote_low is not None:
        low_52w = min(low_52w, float(quote_low))
    range_span = high_52w - low_52w
    if range_span > 0:
        range_position = (last - low_52w) / range_span * 100.0

    return {
        "as_of": history.index[-1].strftime("%Y-%m-%d"),
        "trading_days": int(len(history)),
        "last_close": _round(last, 4),
        "return_1w": _pct(_return_over(close, 5)),
        "return_1m": _pct(_return_over(close, 21)),
        "return_3m": _pct(_return_over(close, 63)),
        "return_6m": _pct(_return_over(close, 126)),
        "return_1y": _pct(_return_over(close, 252)),
        "return_2y": _pct(_return_over(close, 504)),
        "volatility_30d": _pct(vol_30d),
        "rsi14": _round(_rsi(close), 2),
        "sma20": _round(sma20, 4),
        "sma50": _round(sma50, 4),
        "sma200": _round(sma200, 4),
        "high_52w": _round(high_52w, 4),
        "low_52w": _round(low_52w, 4),
        "range_position": _pct(range_position),
        "max_drawdown_1y": _pct(max_dd),
        "support_20d": _round(float(low.tail(20).min()), 4),
        "resistance_20d": _round(float(high.tail(20).max()), 4),
        "avg_volume_20d": int(avg_volume_20d) if avg_volume_20d is not None and math.isfinite(float(avg_volume_20d)) else None,
        "volume_ratio": _round(volume_ratio, 2),
        "trend": trend,
    }


def build_series(history: pd.DataFrame) -> dict:
    dates = [index.strftime("%Y-%m-%d") for index in history.index]
    candles: list[list[float]] = []
    for _, row in history.iterrows():
        candles.append(
            [
                _round(row["Open"], 4) or 0.0,
                _round(row["Close"], 4) or 0.0,
                _round(row["Low"], 4) or 0.0,
                _round(row["High"], 4) or 0.0,
            ]
        )
    close = history["Close"].astype(float)
    ma20 = close.rolling(20, min_periods=20).mean()
    ma50 = close.rolling(50, min_periods=50).mean()
    volume = [int(value) if math.isfinite(float(value)) else 0 for value in history["Volume"].tolist()]
    return {
        "dates": dates,
        "candles": candles,
        "volume": volume,
        "close": _series_to_list(close),
        "ma20": _series_to_list(ma20),
        "ma50": _series_to_list(ma50),
    }


def correlation_matrix(bundles: list[dict]) -> dict:
    series_map: dict[str, pd.Series] = {}
    for bundle in bundles:
        history = bundle.get("history")
        if history is None or history.empty:
            continue
        series_map[bundle["symbol"]] = history["Close"].astype(float).tail(252)
    if len(series_map) < 2:
        return {}
    frame = pd.concat(series_map, axis=1, join="inner").pct_change(fill_method=None).dropna()
    if frame.empty:
        return {}
    corr = frame.corr()
    result: dict[str, dict[str, float | None]] = {}
    for symbol in corr.columns:
        result[symbol] = {
            other: _round(corr.loc[symbol, other], 2)
            for other in corr.columns
        }
    return result


def average_pairwise_correlation(matrix: dict) -> float | None:
    values: list[float] = []
    symbols = list(matrix.keys())
    for i, left in enumerate(symbols):
        for right in symbols[i + 1 :]:
            value = matrix.get(left, {}).get(right)
            if value is not None:
                values.append(float(value))
    if not values:
        return None
    return _round(float(np.mean(values)), 2)
