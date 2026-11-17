from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_REASONING_EFFORT,
    DISCLAIMER,
)
from .universe import lot_size as symbol_lot_size
from .universe import lookup, normalize_symbol, platform_of_symbol

logger = logging.getLogger(__name__)


class AnalysisError(RuntimeError):
    pass


_MARKET_PROFILES = {
    "CN": {
        "label": "A 股",
        "app": "J.T.C.A",
        "currency": "人民币",
        "currency_unit": "元人民币",
        "rule": (
            "请考虑涨跌停限制（主板 ±10%，创业板/科创板 ±20%）、T+1 交易、"
            "停牌风险与政策面因素，不要套用美股交易制度。"
        ),
        "lot_rule": "每手 100 股",
    },
    "HK": {
        "label": "港股",
        "app": "J.T.C.G",
        "currency": "港币",
        "currency_unit": "港元",
        "rule": (
            "请考虑港股 T+0 回转交易、无涨跌停限制、每手股数因股票而异、"
            "T+2 交收以及港元汇率与南向资金因素，不要套用 A 股涨跌停或 T+1 制度。"
        ),
        "lot_rule": "每手股数由具体股票决定，候选数据中的每手股数必须被采用",
    },
    "MIXED": {
        "label": "A 股与港股",
        "app": "J.T.C.A / J.T.C.G",
        "currency": "人民币或港币",
        "currency_unit": "元",
        "rule": (
            "组合同时包含 A 股与港股：A 股遵守 T+1 与涨跌停限制，港股为 T+0、"
            "无涨跌停限制且每手股数因股票而异；请分别按各自交易制度判断。"
        ),
        "lot_rule": "A 股每手 100 股，港股按个股每手股数",
    },
}


def _profile(market: str | None) -> dict:
    return _MARKET_PROFILES.get((market or "CN").upper(), _MARKET_PROFILES["CN"])


def _analysis_system_prompt(market: str = "CN") -> str:
    p = _profile(market)
    return f"""你是 {p['app']} {p['label']}量化分析工具的量化情报分析引擎。
你的任务是基于用户提供的行情、技术指标和新闻，做未来 1 个月的条件式研判。

硬性规则：
1. 只能使用用户提供的数据，不得编造新闻、财报、宏观数据、价格或公司事件。
2. 明确区分已发生的事实、技术推断和条件情景，不要把相关性说成因果关系。
3. 如果新闻不足或数据缺失，必须直接说明，并降低置信度。
4. 所有判断都是概率性的，不承诺涨跌，不给出保证收益的表述。
5. 输出必须是严格合法的 JSON 对象，不要 markdown，不要代码围栏，不要额外说明。
6. 中文输出，股票代码和公司名保持原文。
7. 置信度使用 0 到 100 的整数。支撑位和阻力位使用数字，不带货币符号。
8. 情景区间必须来自给定价格、支撑阻力和波动率，不要给出虚假的精确目标价。
9. 分析对象为{p['label']}，价格以{p['currency']}计价。{p['rule']}
"""


def _screen_system_prompt(market: str = "CN") -> str:
    p = _profile(market)
    return f"""你是 {p['app']} {p['label']}量化分析工具的 {p['label']}初筛引擎。
你的任务是根据用户的最低入股资金，从给定候选池中筛选出适合进一步研究的股票。

硬性规则：
1. 只能从用户给出的候选池中选择，代码必须原样返回，不得编造股票或代码。
2. {p['label']}按手交易，{p['lot_rule']}，最低买入成本 = 现价 × 每手股数。
3. 单只标的一手成本不应超过可用资金的一半，保证还能分散到其他标的；
   一手成本已经超过可用资金的标的不应入选。
4. 行业与风格尽量分散，避免集中在同一板块。
5. 本工具只做短线：优先选择近期（1 到 2 周）量价活跃、流动性好、有短线上涨动能的标的，
   目标是买入后次日或数日内即可兑现短线收益；不推荐需要长期持有的价值股或长期底部盘整的标的。
6. 入选理由是概率性的，不承诺收益。
7. 只输出严格合法的 JSON 对象，不要 markdown，不要代码围栏，不要额外说明。中文输出。
"""


def _allocation_system_prompt(market: str = "CN") -> str:
    p = _profile(market)
    return f"""你是 {p['app']} {p['label']}量化分析工具的资产配置引擎。
你的任务是基于给定候选股票最近一个月的行情、技术指标与新闻，在给定资金内给出最优配置方案。

硬性规则：
1. 只能从用户给出的候选股票中选择，代码必须原样返回。
2. 最多配置用户指定的股票数量，权重合计不超过 100%，可以保留现金。
3. {p['label']}按手交易，{p['lot_rule']}；配置必须考虑一手成本，避免权重对应金额无法成交。
4. 明确区分已发生的事实、技术推断和条件情景，不得编造新闻或数据。
5. 数据不足的标的应降低权重或剔除，并说明原因。
6. 本方案是短线交易方案：以每个交易日均取得正收益为核心目标，建仓后 1 周内兑现收益；
   优先配置近期有量价配合、短线动能明确的标的，不配置长期底仓，不给出“长期持有”类建议。
7. 只输出严格合法的 JSON 对象，不要 markdown，不要代码围栏，不要额外说明。中文输出。
"""


def _watch_system_prompt(market: str = "CN") -> str:
    p = _profile(market)
    return f"""你是 {p['app']} {p['label']}量化分析工具的持仓盯盘引擎。
你的任务是根据用户当前持仓、最新行情、技术指标、新闻和用户选择的投资策略，只给出下一步操作结论。

硬性规则：
1. 只能使用用户提供的数据，不得编造新闻、财报、价格或公司事件。
2. 每只持仓只能输出三种结论之一：持有、部分抛出、全部平仓。
3. 部分抛出必须给出 1 到 99 的卖出比例（占该股票当前持仓股数）；全部平仓为 100；持有为 0。
4. 不输出长篇分析。每只股票的理由不超过 40 字，组合结论不超过 60 字。
5. 策略滑块 0 表示防御，50 表示均衡，100 表示激进。防御策略下优先锁定利润、控制回撤；激进策略下可容忍短期波动，趋势未破坏时继续持有。
6. 这是短线交易系统：以每个交易日均取得正收益为首要目标，只做短线，不做长线。
   持仓已有浮盈时优先在当日内落袋为安；短线趋势走坏、冲高回落、跌破关键均线或出现负面新闻时，
   应及时部分抛出或全部平仓；不得以“长期看好”为理由继续持有走弱或亏损的短线仓位。
   “激进”只代表可多等一个短线波动，不代表把短线仓位转成长线。
7. 当前市场为{p['label']}，配置与卖出需符合{p['lot_rule']}。{p['rule']}
8. 只输出严格合法的 JSON 对象，不要 markdown，不要代码围栏，不要额外说明。中文输出。
"""


SYSTEM_PROMPT = _analysis_system_prompt("CN")
SCREEN_SYSTEM_PROMPT = _screen_system_prompt("CN")
ALLOCATION_SYSTEM_PROMPT = _allocation_system_prompt("CN")
WATCH_SYSTEM_PROMPT = _watch_system_prompt("CN")


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "数据不足"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,.{digits}f}{suffix}"


def _clean_text(value: Any, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _portfolio_data_lines(portfolio: dict, market: str = "CN") -> list[str]:
    p = _profile(market)
    lines: list[str] = []
    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    lines.append(f"分析时间: {generated_at}")
    lines.append(
        f"组合标的: {', '.join(item['symbol'] for item in portfolio.get('symbols', []))}"
    )
    lines.append(
        f"数据快照: {portfolio.get('snapshot_at', '未知')}；历史行情为近两年日线，"
        f"技术指标基于日线计算；新闻窗口为最近 30 天；标的为{p['label']}，"
        f"价格以{p['currency']}计价。"
    )
    liquidity_note = portfolio.get("liquidity_note")
    if liquidity_note:
        lines.append(f"数据说明: {liquidity_note}")

    corr = portfolio.get("correlation") or {}
    if corr:
        lines.append("")
        lines.append("# 组合相关性（近一年日收益率）")
        symbols = list(corr.keys())
        lines.append("代码 " + " ".join(symbols))
        for symbol in symbols:
            row = corr.get(symbol, {})
            values = " ".join(str(row.get(other, "NA")) for other in symbols)
            lines.append(f"{symbol} {values}")

    for item in portfolio.get("symbols", []):
        quote = item.get("quote") or {}
        metrics = item.get("metrics") or {}
        symbol = item.get("symbol", "?")
        lines.append("")
        lines.append(f"# {symbol} / {item.get('name', symbol)} / {quote.get('currency', 'CNY')}")
        lines.append(
            "现价: {price}；日涨跌: {chg}；日涨跌幅: {pct}；前收: {prev}；"
            "开盘: {open}；日内高/低: {high}/{low}；成交量: {volume}；市值: {cap}".format(
                price=_fmt(quote.get("price"), 2),
                chg=_fmt(quote.get("change"), 2),
                pct=_fmt(quote.get("change_pct"), 2, "%"),
                prev=_fmt(quote.get("previous_close"), 2),
                open=_fmt(quote.get("open"), 2),
                high=_fmt(quote.get("day_high"), 2),
                low=_fmt(quote.get("day_low"), 2),
                volume=_fmt(quote.get("volume"), 0),
                cap=_fmt(quote.get("market_cap"), 0),
            )
        )
        lines.append(
            "行情来源: {source}；交易状态: {session}；报价时间: {time} {tz}".format(
                source=quote.get("source", "未知"),
                session=quote.get("session", "未知"),
                time=quote.get("quote_time", "未知"),
                tz=quote.get("quote_timezone", ""),
            )
        )
        lines.append(
            "技术面: RSI14 {rsi}；MA20 {ma20}；MA50 {ma50}；MA200 {ma200}；"
            "52周区间 {low}-{high}；区间位置 {pos}%；30日年化波动 {vol}%；"
            "1周/1月/3月/1年收益 {r1w}% / {r1m}% / {r3m}% / {r1y}%；"
            "20日支撑 {support}；20日阻力 {resistance}；趋势 {trend}".format(
                rsi=_fmt(metrics.get("rsi14"), 1),
                ma20=_fmt(metrics.get("sma20"), 2),
                ma50=_fmt(metrics.get("sma50"), 2),
                ma200=_fmt(metrics.get("sma200"), 2),
                low=_fmt(metrics.get("low_52w"), 2),
                high=_fmt(metrics.get("high_52w"), 2),
                pos=_fmt(metrics.get("range_position"), 1),
                vol=_fmt(metrics.get("volatility_30d"), 1),
                r1w=_fmt(metrics.get("return_1w"), 2),
                r1m=_fmt(metrics.get("return_1m"), 2),
                r3m=_fmt(metrics.get("return_3m"), 2),
                r1y=_fmt(metrics.get("return_1y"), 2),
                support=_fmt(metrics.get("support_20d"), 2),
                resistance=_fmt(metrics.get("resistance_20d"), 2),
                trend=metrics.get("trend", "未知"),
            )
        )

        history = item.get("history") or {}
        dates = history.get("dates") or []
        candles = history.get("candles") or []
        volumes = history.get("volume") or []
        lines.append("最近 22 个交易日日线 (date,open,close,low,high,volume):")
        start = max(0, len(dates) - 22)
        for index in range(start, len(dates)):
            candle = candles[index]
            volume = volumes[index] if index < len(volumes) else 0
            lines.append(
                f"{dates[index]},{candle[0]:.2f},{candle[1]:.2f},"
                f"{candle[2]:.2f},{candle[3]:.2f},{volume}"
            )

        news_items = item.get("news") or []
        lines.append(f"最近 30 天相关新闻 ({len(news_items)} 条，按时间倒序):")
        if not news_items:
            lines.append("无可用新闻。请在新闻判断中明确说明新闻样本不足。")
        for news in news_items[:10]:
            published = news.get("published_at") or "时间未知"
            title = _clean_text(news.get("title"), 160)
            summary = _clean_text(news.get("summary"), 260)
            publisher = _clean_text(news.get("publisher"), 60) or "未知来源"
            lines.append(f"[{published}] {title} ({publisher})")
            if summary:
                lines.append(f"摘要: {summary}")

    return lines


def build_prompt(portfolio: dict, market: str = "CN") -> str:
    lines = _portfolio_data_lines(portfolio, market)
    lines.append("")
    lines.append("# 输出要求")
    lines.append(
        "请输出一个 JSON 对象，字段如下。不要省略 symbols 数组中任何一个标的。"
        "如果某标的数据不足，请把 stance 设为“中性”、confidence 设为低值，并在 thesis 中说明原因。"
    )
    lines.append(
        """
{
  "market_regime": "risk-on 或 neutral 或 risk-off",
  "portfolio_stance": "偏多 或 中性 或 偏空",
  "confidence": 0,
  "summary": "组合层面 2 到 3 句研判，必须引用至少一个数据点",
  "key_themes": ["3 到 5 条主线，每条不超过 30 字"],
  "symbols": [
    {
      "symbol": "代码",
      "stance": "偏多 或 中性 或 偏空",
      "confidence": 0,
      "news_signal": "正面 或 中性 或 负面",
      "thesis": "未来 1 个月的核心判断，2 到 3 句",
      "technical_read": "技术面解读，引用 RSI、均线、支撑阻力或波动率中的至少两个",
      "news_read": "新闻面解读，只能基于给定新闻；没有新闻时明确说明",
      "support": 0,
      "resistance": 0,
      "base_case": {"range": "价格区间", "note": "基准情景说明"},
      "bull_case": {"range": "价格区间", "note": "乐观情景说明"},
      "bear_case": {"range": "价格区间", "note": "悲观情景说明"},
      "catalysts": ["最多 3 条，必须来自给定数据或新闻"],
      "risks": ["最多 3 条"]
    }
  ],
  "portfolio_risks": ["最多 4 条组合层面的风险"],
  "watch_items": ["未来一个月需要跟踪的 3 到 5 个观察项"],
  "disclaimer": "一句话免责声明"
}
        """.strip()
    )
    return "\n".join(lines)


def _affordability_label(capital: float, lot_cost: float | None) -> str:
    if not lot_cost or lot_cost <= 0:
        return "现价暂缺"
    if lot_cost * 2 <= capital:
        return "可买且可分散"
    if lot_cost <= capital:
        return "仅够一手"
    return "一手超预算"


def build_screen_prompt(
    capital: float, pool: list[dict], count: int, market: str = "CN"
) -> str:
    currency = _profile(market)["currency_unit"]
    lines = [
        f"可用资金: {capital:,.0f} {currency}。",
        f"需要筛选的候选数量: {count} 只。",
        "",
        "# 候选股票池",
    ]
    for item in pool:
        price = item.get("price")
        lot_cost = item.get("lot_cost")
        lot = int(item.get("lot_size") or 100)
        if price and lot_cost:
            lines.append(
                f"{item['symbol']} {item['name']} ({item.get('kind', '股票')}) "
                f"现价 {price:.2f} {currency}，每手 {lot} 股，一手成本约 "
                f"{lot_cost:,.0f} {currency}"
                f"（{_affordability_label(capital, lot_cost)}）"
            )
        else:
            lines.append(
                f"{item['symbol']} {item['name']} ({item.get('kind', '股票')}) "
                "现价暂缺，请按经验判断流动性"
            )
    lines.extend(
        [
            "",
            "# 筛选规则",
            "1. 只能从上方候选池中选择，代码必须原样使用。",
            "2. 优先选择一手成本不超过可用资金一半的标的，保证可以分散配置。",
            "3. 行业与风格尽量分散，不要全部集中在同一板块。",
            "4. 优先选择流动性好、近期有短线上涨动能、量价配合活跃的标的。",
            "5. 本工具只做短线，不选长期底部盘整或需要长期持有的标的。",
            "",
            "# 输出要求",
            "只输出 JSON，不要 markdown：",
            json.dumps(
                {
                    "candidates": [
                        {
                            "symbol": pool[0]["symbol"] if pool else "600519.SS",
                            "reason": "不超过 60 字的入选理由",
                        }
                    ],
                    "screen_note": "一句话说明整体筛选思路",
                },
                ensure_ascii=False,
                indent=2,
            ),
        ]
    )
    return "\n".join(lines)


def build_allocation_prompt(
    portfolio: dict, capital: float, max_positions: int, market: str = "CN"
) -> str:
    profile = _profile(market)
    lines = _portfolio_data_lines(portfolio, market)
    lines.extend(
        [
            "",
            "# 配置任务",
            f"可用资金: {capital:,.0f} {profile['currency_unit']}。",
            f"最多配置 {max_positions} 只股票，权重合计不超过 100%，可以保留现金。",
            f"{profile['label']}按手交易，{profile['lot_rule']}，"
            "配置方案必须能用整手成交并控制在预算内。",
            "本方案只做短线：以每个交易日均取得正收益为核心目标，1 周内兑现收益，优先近期动能明确的标的，不配置长线底仓。",
            "",
            "# 输出要求",
            "只输出 JSON，不要 markdown：",
            json.dumps(
                {
                    "allocations": [
                        {
                            "symbol": "600519.SS",
                            "weight": 30,
                            "role": "核心 / 卫星 / 防御",
                            "reason": "入选与配置理由，不超过 80 字",
                            "entry": "建仓节奏或价格区间，不超过 60 字",
                        }
                    ],
                    "risk_level": "稳健 或 均衡 或 进取",
                    "summary": "组合层面 2 到 3 句配置说明",
                    "risks": ["最多 4 条"],
                    "watch_items": ["最多 4 条"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        ]
    )
    return "\n".join(lines)


def _watch_strategy_label(score: int) -> str:
    value = max(0, min(100, int(score)))
    if value <= 33:
        return "防御"
    if value <= 66:
        return "均衡"
    return "激进"


def build_watch_prompt(
    portfolio: dict,
    holdings: list[dict],
    strategy_score: int,
    market: str = "CN",
) -> str:
    currency = _profile(market)["currency_unit"]
    score = max(0, min(100, int(strategy_score)))
    label = _watch_strategy_label(score)
    generated_at = datetime.now(timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M %Z"
    )
    item_map = {
        item.get("symbol"): item for item in portfolio.get("symbols", [])
    }
    total_value = sum(float(item.get("market_value") or 0) for item in holdings)
    lines = [
        f"分析时间: {generated_at}",
        f"投资策略滑块: {score}/100（0 防御，50 均衡，100 激进），本次按“{label}”执行。",
        "交易周期：短线（以 1 周以内为主），目标是每个交易日尽量锁定正收益，不做长线持有。",
        "防御：当日有盈利优先落袋为安；走势转弱或新闻明显负面时部分或全部抛出。",
        "均衡：短线趋势或新闻明显恶化时减仓，有浮盈时优先兑现。",
        "激进：仍按 1 到 3 个交易日的短线维度操作，趋势未破坏时可继续持有，但不转为长线。",
        "",
        "# 当前持仓",
    ]
    if not holdings:
        lines.append("当前没有持仓。")
    for holding in holdings:
        symbol = holding.get("symbol", "?")
        item = item_map.get(symbol) or {}
        metrics = item.get("metrics") or {}
        weight = (
            round(float(holding.get("market_value") or 0) / total_value * 100, 1)
            if total_value
            else 0.0
        )
        item_currency = (
            _profile(platform_of_symbol(symbol))["currency_unit"]
            if (market or "").upper() == "MIXED"
            else currency
        )
        lines.append(
            f"{symbol} {holding.get('name') or symbol}：持仓 {holding.get('shares', 0)} 股"
            f"（每手 {holding.get('lot_size', 100)} 股），"
            f"成本 {_fmt(holding.get('buy_price'))} {item_currency}，"
            f"现价 {_fmt(holding.get('price'))} {item_currency}，"
            f"市值 {_fmt(holding.get('market_value'))} {item_currency}，"
            f"浮动盈亏 {_fmt(holding.get('profit'))} {item_currency}"
            f"（{_fmt(holding.get('profit_pct'))}%），仓位占比 {weight}%。"
        )
        if metrics:
            lines.append(
                "技术面: RSI14 {rsi}；MA20 {ma20}；MA50 {ma50}；"
                "1周/1月/3月收益 {r1w}% / {r1m}% / {r3m}%；"
                "30日年化波动 {vol}%；趋势 {trend}".format(
                    rsi=_fmt(metrics.get("rsi14"), 1),
                    ma20=_fmt(metrics.get("sma20")),
                    ma50=_fmt(metrics.get("sma50")),
                    r1w=_fmt(metrics.get("return_1w")),
                    r1m=_fmt(metrics.get("return_1m")),
                    r3m=_fmt(metrics.get("return_3m")),
                    vol=_fmt(metrics.get("volatility_30d"), 1),
                    trend=metrics.get("trend", "未知"),
                )
            )
        else:
            lines.append("技术面: 行情数据暂缺。")
        news_items = item.get("news") or []
        if news_items:
            lines.append(f"新闻（最近 {min(len(news_items), 6)} 条）:")
            for news in news_items[:6]:
                title = _clean_text(news.get("title"), 120)
                if title:
                    lines.append(f"- [{news.get('published_at') or '时间未知'}] {title}")
        else:
            lines.append("新闻: 无可用新闻。")
        lines.append("")

    lines.extend(
        [
            "# 输出要求",
            "只输出 JSON，不要 markdown，不要解释。每只持仓都必须给出结论：",
            json.dumps(
                {
                    "summary": "组合结论，不超过 60 字",
                    "positions": [
                        {
                            "symbol": "代码",
                            "action": "持有 或 部分抛出 或 全部平仓",
                            "sell_ratio": 0,
                            "reason": "不超过 40 字",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            "sell_ratio 为部分抛出时占当前持仓股数的百分比，1 到 99；持有为 0；全部平仓为 100。",
        ]
    )
    return "\n".join(lines)


def _watch_action(value: Any) -> str:
    text = str(value or "").strip().lower()
    if any(
        token in text
        for token in ("部分", "减仓", "partial", "trim", "reduce")
    ):
        return "部分抛出"
    if any(
        token in text
        for token in (
            "全部平仓",
            "全部抛出",
            "全部卖出",
            "清仓",
            "平仓",
            "close",
            "sell all",
            "exit",
        )
    ):
        return "全部平仓"
    if any(token in text for token in ("卖出", "sell")):
        return "部分抛出"
    return "持有"


def _watch_ratio(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace("%", ""))
        if not match:
            return default
        number = float(match.group(0))
    return max(0.0, min(100.0, number))


def _normalize_watch(
    raw: dict, holdings: list[dict], strategy_score: int
) -> dict:
    entries = raw.get("positions")
    if isinstance(entries, dict):
        entries = [
            {"symbol": key, **value}
            for key, value in entries.items()
            if isinstance(value, dict)
        ]
    if not isinstance(entries, list):
        entries = []
    by_symbol: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        symbol = _screen_symbol(
            entry.get("symbol") or entry.get("code") or entry.get("ticker") or ""
        )
        if symbol:
            by_symbol[symbol] = entry

    results: list[dict] = []
    for holding in holdings:
        symbol = holding.get("symbol", "")
        entry = by_symbol.get(symbol) or {}
        action = _watch_action(
            entry.get("action") or entry.get("decision") or entry.get("conclusion")
        )
        shares = int(holding.get("shares") or 0)
        ratio = _watch_ratio(
            entry.get(
                "sell_ratio",
                entry.get("ratio", entry.get("percent", entry.get("sell_percent"))),
            )
        )
        if action == "部分抛出":
            if ratio <= 0:
                ratio = 50.0
            sell_shares = max(1, int(round(shares * ratio / 100)))
            if sell_shares >= shares:
                action = "全部平仓"
                ratio = 100.0
                sell_shares = shares
        elif action == "全部平仓":
            ratio = 100.0
            sell_shares = shares
        else:
            ratio = 0.0
            sell_shares = 0
        reason = _clean_text(
            entry.get("reason")
            or entry.get("conclusion")
            or entry.get("note")
            or entry.get("summary"),
            80,
        )
        if not reason:
            reason = "数据不足，继续观察。" if not entry else "维持当前仓位。"
        results.append(
            {
                "symbol": symbol,
                "name": holding.get("name") or symbol,
                "shares": shares,
                "buy_price": holding.get("buy_price"),
                "price": holding.get("price"),
                "market_value": holding.get("market_value"),
                "profit": holding.get("profit"),
                "profit_pct": holding.get("profit_pct"),
                "action": action,
                "sell_ratio": round(ratio, 1),
                "sell_shares": sell_shares,
                "reason": reason,
            }
        )

    summary = _clean_text(
        raw.get("summary") or raw.get("conclusion") or raw.get("note"), 160
    )
    if not summary:
        summary = "本次未发现需要调整的持仓，维持当前仓位。"
    return {
        "strategy": max(0, min(100, int(strategy_score))),
        "strategy_label": _watch_strategy_label(strategy_score),
        "summary": summary,
        "positions": results,
    }


def _request_meta(body: dict, started: float) -> dict:
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    usage = body.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    return {
        "model": body.get("model") or DEEPSEEK_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": elapsed_ms,
        "reasoning_effort": DEEPSEEK_REASONING_EFFORT or None,
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "reasoning_tokens": details.get("reasoning_tokens"),
        },
    }


def _screen_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper().replace(" ", "")
    match = re.fullmatch(r"(?:SH|SZ|BJ)\.?(\d{6})", raw)
    if match:
        raw = match.group(1)
    elif re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", raw):
        raw = raw.split(".", 1)[0]
    elif re.fullmatch(r"[01]\.\d{6}", raw):
        raw = raw.split(".", 1)[1]
    else:
        # 港股：00700 / 0700.HK / HK00700 等写法统一为 5 位代码。
        match = re.fullmatch(r"(?:HK)?\.?(\d{1,5})(?:\.HK)?", raw)
        if match:
            raw = f"{match.group(1).zfill(5)}.HK"
    return normalize_symbol(raw)


def _normalize_candidates(raw: dict, pool: list[dict], count: int) -> list[dict]:
    pool_map = {item["symbol"]: item for item in pool}
    name_map = {item["name"]: item["symbol"] for item in pool}
    entries = raw.get("candidates")
    if not isinstance(entries, list):
        entries = []
    result: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            symbol_raw, reason = entry, ""
        elif isinstance(entry, dict):
            symbol_raw = (
                entry.get("symbol") or entry.get("code") or entry.get("ticker") or ""
            )
            reason = entry.get("reason") or entry.get("logic") or entry.get("note") or ""
        else:
            continue
        symbol = _screen_symbol(symbol_raw)
        item = pool_map.get(symbol)
        if not item:
            mapped = name_map.get(str(symbol_raw).strip())
            if mapped:
                symbol = mapped
                item = pool_map[mapped]
        if not item or symbol in seen:
            continue
        seen.add(symbol)
        result.append(
            {
                "symbol": symbol,
                "name": item["name"],
                "reason": _clean_text(reason, 120),
            }
        )
        if len(result) >= count:
            break
    return result


def _weight_number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(100.0, float(value)))
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return 0.0
    return max(0.0, min(100.0, float(match.group(0))))


async def screen_candidates(
    capital: float, pool: list[dict], count: int = 8, market: str = "CN"
) -> dict:
    if not DEEPSEEK_API_KEY:
        raise AnalysisError("未配置 DEEPSEEK_API_KEY，请在 .env 中填写")
    prompt = build_screen_prompt(capital, pool, count, market)
    payload: dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _screen_system_prompt(market)},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 16000,
        "response_format": {"type": "json_object"},
    }
    if DEEPSEEK_REASONING_EFFORT:
        payload["reasoning_effort"] = DEEPSEEK_REASONING_EFFORT

    started = time.perf_counter()
    body = await _post(payload)
    choices = body.get("choices") or []
    if not choices:
        raise AnalysisError("模型未返回筛选结果")
    if choices[0].get("finish_reason") == "length":
        raise AnalysisError("筛选结果被截断，请重试或减少候选数量")
    content = (choices[0].get("message") or {}).get("content") or ""
    raw = _extract_json(content)
    candidates = _normalize_candidates(raw, pool, count)
    if not candidates:
        raise AnalysisError("模型未返回有效候选股票，请重试")
    return {
        "capital": capital,
        "candidates": candidates,
        "note": _clean_text(raw.get("screen_note"), 300),
        "meta": _request_meta(body, started),
    }


def _normalize_allocation(
    raw: dict,
    portfolio: dict,
    capital: float,
    max_positions: int,
    market: str = "CN",
) -> dict:
    items = {item["symbol"]: item for item in portfolio.get("symbols", [])}
    name_map = {
        item.get("name"): item["symbol"]
        for item in portfolio.get("symbols", [])
        if item.get("name")
    }
    entries = raw.get("allocations")
    if isinstance(entries, dict):
        entries = [
            {"symbol": key, **value}
            for key, value in entries.items()
            if isinstance(value, dict)
        ]
    if not isinstance(entries, list):
        entries = []

    proposals: list[tuple[str, float, dict]] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            symbol, weight, payload = _screen_symbol(entry), 0.0, {}
            if symbol not in items:
                mapped = name_map.get(entry.strip())
                if mapped:
                    symbol = mapped
        elif isinstance(entry, dict):
            raw_symbol = entry.get("symbol") or entry.get("code") or ""
            symbol = _screen_symbol(raw_symbol)
            if symbol not in items:
                mapped = name_map.get(str(raw_symbol).strip())
                if mapped:
                    symbol = mapped
            weight = _weight_number(
                entry.get("weight", entry.get("allocation", entry.get("percent")))
            )
            payload = entry
        else:
            continue
        if symbol not in items or symbol in seen:
            continue
        seen.add(symbol)
        proposals.append((symbol, weight, payload))

    if not proposals:
        raise AnalysisError("模型未返回有效的配置方案，请重试")

    proposals.sort(key=lambda item: item[1], reverse=True)
    proposals = proposals[:max_positions]
    total_weight = sum(weight for _, weight, _ in proposals)
    if total_weight <= 0:
        raise AnalysisError("模型返回的配置权重无效，请重试")
    if total_weight > 100:
        scale = 100.0 / total_weight
        proposals = [(symbol, weight * scale, payload) for symbol, weight, payload in proposals]

    allocations: list[dict] = []
    invested = 0.0
    for symbol, weight, payload in proposals:
        item = items[symbol]
        quote = item.get("quote") or {}
        price = quote.get("price")
        if price is None:
            price = (item.get("metrics") or {}).get("last_close")
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None
        if not price or price <= 0:
            continue
        budget = capital * weight / 100.0
        lot = symbol_lot_size(symbol)
        lots = int(budget // (price * lot))
        shares = lots * lot
        if shares <= 0:
            continue
        amount = round(shares * price, 2)
        invested += amount
        fallback = lookup(symbol)
        allocations.append(
            {
                "symbol": symbol,
                "name": item.get("name") or (fallback["name"] if fallback else symbol),
                "weight": round(weight, 1),
                "actual_weight": round(amount / capital * 100, 1),
                "shares": shares,
                "lot_size": lot,
                "amount": amount,
                "price": round(price, 4),
                "role": _clean_text(payload.get("role"), 30) or "配置",
                "reason": _clean_text(
                    payload.get("reason") or payload.get("thesis"), 200
                ),
                "entry": _clean_text(payload.get("entry"), 160),
            }
        )

    if not allocations:
        raise AnalysisError(
            "按当前资金无法买入候选股票的一手，请提高资金或重新筛选"
        )

    invested = round(invested, 2)
    unallocated = round(max(0.0, capital - invested), 2)
    return {
        "capital": capital,
        "invested": invested,
        "unallocated_cash": unallocated,
        "cash_weight": round(unallocated / capital * 100, 1),
        "allocations": allocations,
        "risk_level": _clean_text(raw.get("risk_level"), 20),
        "summary": _clean_text(raw.get("summary"), 600)
        or "模型未提供配置说明。",
        "risks": _as_list(raw.get("risks"), 4, 200),
        "watch_items": _as_list(raw.get("watch_items"), 4, 180),
    }


async def optimize_allocation(
    portfolio: dict, capital: float, max_positions: int, market: str = "CN"
) -> dict:
    if not DEEPSEEK_API_KEY:
        raise AnalysisError("未配置 DEEPSEEK_API_KEY，请在 .env 中填写")
    prompt = build_allocation_prompt(portfolio, capital, max_positions, market)
    payload: dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _allocation_system_prompt(market)},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 32000,
        "response_format": {"type": "json_object"},
    }
    if DEEPSEEK_REASONING_EFFORT:
        payload["reasoning_effort"] = DEEPSEEK_REASONING_EFFORT

    started = time.perf_counter()
    body = await _post(payload)
    choices = body.get("choices") or []
    if not choices:
        raise AnalysisError("模型未返回配置结果")
    if choices[0].get("finish_reason") == "length":
        raise AnalysisError("配置结果被截断，请重试或减少候选数量")
    content = (choices[0].get("message") or {}).get("content") or ""
    raw = _extract_json(content)
    result = _normalize_allocation(raw, portfolio, capital, max_positions, market)
    result["meta"] = _request_meta(body, started)
    return result


async def watch_holdings(
    portfolio: dict,
    holdings: list[dict],
    strategy_score: int,
    market: str = "CN",
) -> dict:
    if not DEEPSEEK_API_KEY:
        raise AnalysisError("智能盯盘服务暂不可用，请稍后重试")
    if not holdings:
        return {
            "strategy": max(0, min(100, int(strategy_score))),
            "strategy_label": _watch_strategy_label(strategy_score),
            "summary": "当前没有持仓，无需盯盘。",
            "positions": [],
            "meta": {},
        }
    prompt = build_watch_prompt(portfolio, holdings, strategy_score, market)
    payload: dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _watch_system_prompt(market)},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }
    if DEEPSEEK_REASONING_EFFORT:
        payload["reasoning_effort"] = DEEPSEEK_REASONING_EFFORT

    started = time.perf_counter()
    body = await _post(payload)
    choices = body.get("choices") or []
    if not choices:
        raise AnalysisError("模型未返回盯盘结论，请稍后重试")
    if choices[0].get("finish_reason") == "length":
        raise AnalysisError("盯盘结论被截断，请重试")
    content = (choices[0].get("message") or {}).get("content") or ""
    raw = _extract_json(content)
    result = _normalize_watch(raw, holdings, strategy_score)
    result["meta"] = _request_meta(body, started)
    return result


def _headers() -> dict[str, str]:
    if not DEEPSEEK_API_KEY:
        raise AnalysisError("未配置 DEEPSEEK_API_KEY")
    return {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }


async def _post(payload: dict) -> dict:
    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(180.0, connect=15.0),
                follow_redirects=True,
            ) as client:
                response = await client.post(url, headers=_headers(), json=payload)
                if response.status_code == 200:
                    return response.json()
                detail = ""
                try:
                    body = response.json()
                    detail = str(body.get("error", body.get("message", "")))[:400]
                except Exception:
                    detail = response.text[:400]
                if response.status_code == 400 and "response_format" in payload:
                    retry_payload = dict(payload)
                    retry_payload.pop("response_format", None)
                    payload = retry_payload
                    continue
                if (
                    response.status_code in (400, 422)
                    and "reasoning_effort" in payload
                    and "reasoning_effort" in detail.lower()
                ):
                    logger.warning("接口不接受 reasoning_effort，已降级重试")
                    retry_payload = dict(payload)
                    retry_payload.pop("reasoning_effort", None)
                    payload = retry_payload
                    continue
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if response.status_code == 401:
                    raise AnalysisError("DeepSeek API Key 无效或已失效")
                if response.status_code == 402:
                    raise AnalysisError("DeepSeek 账户余额不足，请充值后重试")
                if response.status_code == 429:
                    raise AnalysisError("DeepSeek 请求过于频繁，请稍后重试")
                raise AnalysisError(
                    f"DeepSeek 请求失败 ({response.status_code}): {detail or '未知错误'}"
                )
        except AnalysisError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise AnalysisError("无法连接 DeepSeek，请检查网络后重试") from exc
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(1.0)
                continue
            raise AnalysisError(f"DeepSeek 调用异常: {exc}") from exc
    raise AnalysisError(f"DeepSeek 调用失败: {last_error}")


def _extract_json(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    raise AnalysisError("模型返回内容不是合法 JSON，请重试")


def _clamp_confidence(value: Any, default: int = 50) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, number))


def _stance(value: Any) -> str:
    text = str(value or "").lower()
    if any(token in text for token in ("偏多", "看多", "bull", "positive", "多")):
        return "偏多"
    if any(token in text for token in ("偏空", "看空", "bear", "negative", "空")):
        return "偏空"
    return "中性"


def _news_signal(value: Any) -> str:
    text = str(value or "").lower()
    if any(token in text for token in ("正面", "积极", "positive", "bull")):
        return "正面"
    if any(token in text for token in ("负面", "消极", "negative", "bear")):
        return "负面"
    return "中性"


def _as_list(value: Any, limit: int = 6, item_limit: int = 180) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for entry in value[:limit]:
        text = _clean_text(entry, item_limit)
        if text:
            result.append(text)
    return result


def _price_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    return round(float(match.group(0)), 4)


def _scenario(value: Any) -> dict:
    if isinstance(value, dict):
        price_range = _clean_text(value.get("range"), 80) or "数据不足"
        note = _clean_text(value.get("note"), 260)
        return {"range": price_range, "note": note}
    if isinstance(value, str) and value.strip():
        return {"range": "数据不足", "note": _clean_text(value, 260)}
    return {"range": "数据不足", "note": ""}


def _normalize_result(raw: dict, portfolio: dict, meta: dict) -> dict:
    symbols_in = portfolio.get("symbols", [])
    expected = [item["symbol"] for item in symbols_in]
    raw_symbols = raw.get("symbols")
    if isinstance(raw_symbols, dict):
        raw_symbols = [
            {"symbol": key, **value}
            for key, value in raw_symbols.items()
            if isinstance(value, dict)
        ]
    if not isinstance(raw_symbols, list):
        raw_symbols = []
    by_symbol: dict[str, dict] = {}
    for item in raw_symbols:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).upper().strip()
        if symbol:
            by_symbol[symbol] = item

    normalized_symbols = []
    for portfolio_item in symbols_in:
        symbol = portfolio_item["symbol"]
        metrics = portfolio_item.get("metrics") or {}
        item = by_symbol.get(symbol, {})
        if not item:
            item = {
                "thesis": "模型未返回该标的的单独判断，请结合下方组合结论并谨慎解读。",
                "technical_read": "数据不足。",
                "news_read": "数据不足。",
                "confidence": 0,
                "stance": "中性",
                "news_signal": "中性",
                "support": metrics.get("support_20d"),
                "resistance": metrics.get("resistance_20d"),
                "base_case": {"range": "数据不足", "note": ""},
                "bull_case": {"range": "数据不足", "note": ""},
                "bear_case": {"range": "数据不足", "note": ""},
                "catalysts": [],
                "risks": [],
            }
        normalized_symbols.append(
            {
                "symbol": symbol,
                "name": portfolio_item.get("name", symbol),
                "stance": _stance(item.get("stance")),
                "confidence": _clamp_confidence(item.get("confidence"), 15 if not by_symbol.get(symbol) else 50),
                "news_signal": _news_signal(item.get("news_signal")),
                "thesis": _clean_text(item.get("thesis"), 420) or "模型未提供核心判断。",
                "technical_read": _clean_text(item.get("technical_read"), 420) or "数据不足。",
                "news_read": _clean_text(item.get("news_read"), 420) or "数据不足。",
                "support": _price_number(item.get("support")) or metrics.get("support_20d"),
                "resistance": _price_number(item.get("resistance")) or metrics.get("resistance_20d"),
                "base_case": _scenario(item.get("base_case")),
                "bull_case": _scenario(item.get("bull_case")),
                "bear_case": _scenario(item.get("bear_case")),
                "catalysts": _as_list(item.get("catalysts"), 3, 180),
                "risks": _as_list(item.get("risks"), 3, 180),
            }
        )

    regime_raw = str(raw.get("market_regime", "")).lower()
    if any(token in regime_raw for token in ("risk-on", "risk on", "偏好", "乐观", "进攻")):
        regime = "risk-on"
    elif any(token in regime_raw for token in ("risk-off", "risk off", "避险", "谨慎", "防守")):
        regime = "risk-off"
    else:
        regime = "neutral"

    result = {
        "market_regime": regime,
        "portfolio_stance": _stance(raw.get("portfolio_stance")),
        "confidence": _clamp_confidence(raw.get("confidence"), 50),
        "summary": _clean_text(raw.get("summary"), 900) or "模型未提供组合摘要。",
        "key_themes": _as_list(raw.get("key_themes"), 5, 100),
        "symbols": normalized_symbols,
        "portfolio_risks": _as_list(raw.get("portfolio_risks"), 4, 220),
        "watch_items": _as_list(raw.get("watch_items"), 5, 180),
        "disclaimer": _clean_text(raw.get("disclaimer"), 300)
        or "本分析由 AI 生成，仅用于研究，不构成投资建议。",
    }
    result["meta"] = meta
    result["expected_symbols"] = expected
    return result


async def analyze_portfolio(portfolio: dict, market: str = "CN") -> dict:
    if not DEEPSEEK_API_KEY:
        raise AnalysisError("未配置 DEEPSEEK_API_KEY，请在 .env 中填写")
    prompt = build_prompt(portfolio, market)
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _analysis_system_prompt(market)},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 32000,
        "response_format": {"type": "json_object"},
    }
    if DEEPSEEK_REASONING_EFFORT:
        payload["reasoning_effort"] = DEEPSEEK_REASONING_EFFORT
    started = time.perf_counter()
    body = await _post(payload)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    choices = body.get("choices") or []
    if not choices:
        raise AnalysisError("DeepSeek 未返回分析内容")
    if choices[0].get("finish_reason") == "length":
        raise AnalysisError("模型输出被截断，请重试或减少同时分析的标的数量")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    raw = _extract_json(content)
    usage = body.get("usage") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    meta = {
        "model": body.get("model") or DEEPSEEK_MODEL,
        "reasoning_effort": DEEPSEEK_REASONING_EFFORT or None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": elapsed_ms,
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "reasoning_tokens": completion_details.get("reasoning_tokens"),
        },
        "data_as_of": max(
            (
                item.get("metrics", {}).get("as_of")
                for item in portfolio.get("symbols", [])
                if item.get("metrics", {}).get("as_of")
            ),
            default=None,
        ),
    }
    return _normalize_result(raw, portfolio, meta)
