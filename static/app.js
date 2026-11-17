(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const PLATFORM_KEY = "jtca.platform.v1";
  const WATCH_KEYS = {
    CN: "nocturne.watchlist.a2",
    HK: "jtca.watchlist.hk.v1",
  };
  const LEGACY_SELECTED_KEY = "nocturne.selected.v1";
  const AIWATCH_KEY = "jtca.aiwatch.v1";
  const AIWATCH_POLL_MS = 60 * 1000;
  const MAX_WATCHLIST = 12;
  const POLL_MS = 45000;
  const SYMBOL_RE = /^[A-Z0-9^][A-Z0-9.\-]{0,14}$/;
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const RANGE_LABELS = {
    DAY: "今日",
    WEEK: "本周",
    MONTH: "近1月",
    "3M": "三月",
    "6M": "六月",
    YEAR: "今年",
  };
  const MARKET_META = {
    "000001.SS": { name: "上证指数", code: "000001" },
    "399001.SZ": { name: "深证成指", code: "399001" },
    "399006.SZ": { name: "创业板指", code: "399006" },
    "000300.SS": { name: "沪深300", code: "000300" },
    "^HSI": { name: "恒生指数", code: "HSI" },
    "^HSCE": { name: "国企指数", code: "HSCE" },
    "^HSTECH": { name: "恒生科技", code: "HSTECH" },
  };
  const DISPLAY_MODEL = "J.T.C.A AI";
  const VIP_NAMES = { 0: "普通用户", 1: "黄金VIP", 2: "白金VIP", 3: "钻石VIP" };
  const CN_FALLBACK_CONFIG = {
    platform: "CN",
    app_name: "J.T.C.A",
    subtitle: "A股量化分析工具",
    market_label: "A 股市场",
    market_short: "A股",
    model: DISPLAY_MODEL,
    ai_configured: true,
    max_selection: 5,
    default_watchlist: ["600519.SS", "300750.SZ", "601318.SS", "000858.SZ", "002594.SZ", "600036.SS"],
    default_selected: [],
    market_symbols: ["000001.SS", "399001.SZ", "399006.SZ", "000300.SS"],
    lot_note: "A 股每手 100 股",
    session_note: "北京时间 09:30-11:30 / 13:00-15:00",
  };
  const HK_FALLBACK_CONFIG = {
    platform: "HK",
    app_name: "J.T.C.G",
    subtitle: "港股量化分析工具",
    market_label: "港股市场",
    market_short: "港股",
    model: "J.T.C.G AI",
    ai_configured: true,
    max_selection: 5,
    default_watchlist: ["00700.HK", "09988.HK", "03690.HK", "01810.HK", "00941.HK", "00388.HK"],
    default_selected: [],
    market_symbols: ["^HSI", "^HSCE", "^HSTECH"],
    lot_note: "港股每手股数因股票而异",
    session_note: "香港时间 09:30-12:00 / 13:00-16:00",
  };

  function fallbackConfig(platform) {
    return { ...(platform === "HK" ? HK_FALLBACK_CONFIG : CN_FALLBACK_CONFIG) };
  }

  function readPlatform() {
    try {
      const stored = window.localStorage.getItem(PLATFORM_KEY);
      return stored === "HK" ? "HK" : "CN";
    } catch (_error) {
      return "CN";
    }
  }

  function persistPlatform() {
    try {
      window.localStorage.setItem(PLATFORM_KEY, state.platform);
    } catch (_error) {
      // localStorage 不可用时仍可在本次会话内切换。
    }
  }

  function watchKey() {
    return WATCH_KEYS[state.platform] || WATCH_KEYS.CN;
  }

  function platformParam() {
    return `platform=${encodeURIComponent(state.platform)}`;
  }

  function isHkSymbol(symbol) {
    const upper = String(symbol || "").toUpperCase();
    return upper.endsWith(".HK") || upper === "^HSI" || upper === "^HSCE" || upper === "^HSTECH";
  }

  function symbolLotSize(symbol, fallback = 100) {
    const quote = state.liveQuotes.get(symbol) || state.lastQuotes.get(symbol);
    const bundle = state.bundles.get(symbol);
    const raw =
      (quote && quote.lot_size) ||
      (bundle && bundle.quote && bundle.quote.lot_size) ||
      fallback;
    const lot = Number(raw);
    return Number.isFinite(lot) && lot > 0 ? Math.round(lot) : 100;
  }
  const ICON = {
    external: '<svg class="icon" aria-hidden="true"><use href="#i-external"></use></svg>',
    chevron: '<svg class="icon" aria-hidden="true"><use href="#i-chevron"></use></svg>',
    spark: '<svg class="icon" aria-hidden="true"><use href="#i-spark"></use></svg>',
    refresh: '<svg class="icon" aria-hidden="true"><use href="#i-refresh"></use></svg>',
    x: '<svg class="icon" aria-hidden="true"><use href="#i-x"></use></svg>',
  };

  const state = {
    platform: readPlatform(),
    config: fallbackConfig(readPlatform()),
    maxSelection: 5,
    watchlist: [],
    selected: [],
    lastQuotes: new Map(),
    bundles: new Map(),
    portfolio: null,
    activeSymbol: null,
    detailSymbol: null,
    range: "6M",
    mode: "candle",
    newsFilter: "all",
    newsLimit: 8,
    aiState: "idle",
    analysisPayload: null,
    analysisStartedAt: 0,
    analysisTimer: null,
    loadingPortfolio: false,
    portfolioController: null,
    analysisController: null,
    quoteController: null,
    portfolioSeq: 0,
    analysisSeq: 0,
    quoteSeq: 0,
    marketSeq: 0,
    searchSeq: 0,
    searchController: null,
    searchResults: [],
    searchActive: -1,
    portfolioTimer: null,
    searchTimer: null,
    watchQuoteTimer: null,
    chart: null,
    chartObserver: null,
    chartResizeBound: false,
    booted: false,
    lastQuoteFetch: 0,
    refreshBusy: false,
    screenerBusy: false,
    screenerSeq: 0,
    screenerController: null,
    lastAllocation: null,
    autoTradeBusy: false,
    manualBuyBusy: false,
    closePositionBusy: false,
    closePositionSymbol: null,
    sellMode: "full",
    sellShares: 0,
    isSimulated: false,
    aiWatchEnabled: false,
    aiWatchBusy: false,
    aiWatchStrategy: 50,
    aiWatchTimer: null,
    aiWatchResult: null,
    accountSummary: null,
    accountSummaryBusy: false,
    intraday: new Map(),
    intradayErrors: new Map(),
    intradayPending: new Set(),
    intradayControllers: new Map(),
    intradayTimer: null,
    liveQuotes: new Map(),
    liveController: null,
    liveSeq: 0,
    lastWeekLiveAt: 0,
  };

  // -------------------------------------------------------------------------
  // Utilities
  // -------------------------------------------------------------------------

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function isAbortError(error) {
    return Boolean(error && (error.name === "AbortError" || error.code === 20));
  }

  function toFiniteNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function formatPrice(value, digits) {
    const number = toFiniteNumber(value);
    if (number === null) return "--";
    const places = digits == null ? (Math.abs(number) < 1 ? 3 : 2) : digits;
    return number.toLocaleString("en-US", {
      minimumFractionDigits: places,
      maximumFractionDigits: places,
    });
  }

  function formatPercent(value, signed = true) {
    const number = toFiniteNumber(value);
    if (number === null) return "--";
    const prefix = signed && number > 0 ? "+" : "";
    return `${prefix}${number.toFixed(2)}%`;
  }

  function formatSignedPrice(value) {
    const number = toFiniteNumber(value);
    if (number === null) return "--";
    const prefix = number > 0 ? "+" : "";
    return `${prefix}${formatPrice(number)}`;
  }

  function formatVolume(value) {
    const number = toFiniteNumber(value);
    if (number === null) return "--";
    if (Math.abs(number) >= 1e8) return `${(number / 1e8).toFixed(2)}亿`;
    if (Math.abs(number) >= 1e4) return `${(number / 1e4).toFixed(1)}万`;
    return Math.round(number).toLocaleString("en-US");
  }

  function formatVolumeAxis(value) {
    const number = toFiniteNumber(value);
    if (number === null) return "";
    if (Math.abs(number) >= 1e8) return `${(number / 1e8).toFixed(1)}亿`;
    if (Math.abs(number) >= 1e4) return `${Math.round(number / 1e4)}万`;
    return String(Math.round(number));
  }

  function toneClass(value) {
    const number = toFiniteNumber(value);
    if (number === null || number === 0) return "flat";
    return number > 0 ? "up" : "down";
  }

  function truncateText(value, limit) {
    const text = String(value || "").trim();
    if (text.length <= limit) return text;
    return `${text.slice(0, limit).trimEnd()}…`;
  }

  function stripHtml(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    try {
      const doc = new DOMParser().parseFromString(text, "text/html");
      return (doc.body.textContent || "").replace(/\s+/g, " ").trim();
    } catch (_error) {
      return text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    }
  }

  function safeHttpUrl(value) {
    if (!value) return "";
    try {
      const url = new URL(String(value), window.location.origin);
      if (url.protocol === "http:" || url.protocol === "https:") return url.href;
    } catch (_error) {
      return "";
    }
    return "";
  }

  function normalizeSymbol(value) {
    const raw = String(value || "").trim().toUpperCase().replace(/\s+/g, "");
    if (/^\d{6}$/.test(raw)) {
      if (raw[0] === "5" || raw[0] === "6" || raw[0] === "9") return `${raw}.SS`;
      if (raw[0] === "4" || raw[0] === "8") return `${raw}.BJ`;
      return `${raw}.SZ`;
    }
    return raw;
  }

  function sanitizeSymbolList(value) {
    if (!Array.isArray(value)) return null;
    const out = [];
    for (const raw of value) {
      if (typeof raw !== "string") continue;
      const symbol = normalizeSymbol(raw);
      if (!SYMBOL_RE.test(symbol) || out.includes(symbol)) continue;
      out.push(symbol);
    }
    return out;
  }

  function readStore(key) {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw === null) return null;
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? sanitizeSymbolList(parsed) : null;
    } catch (_error) {
      return null;
    }
  }

  function writeStore(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (_error) {
      // Local storage can be unavailable in private mode. State still works.
    }
  }

  function persistState() {
    writeStore(watchKey(), state.watchlist);
  }

  function selectedSignature(list) {
    return (list || state.selected).join("|");
  }

  function createIcon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#i-${name}`);
    svg.appendChild(use);
    return svg;
  }

  async function apiJson(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    let response;
    try {
      response = await fetch(path, { ...options, headers });
    } catch (error) {
      if (isAbortError(error)) throw error;
      throw new Error("无法连接本地服务，请确认后端已经启动");
    }
    const text = await response.text();
    let body = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch (_error) {
        body = null;
      }
    }
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      redirectToLogin();
      throw new Error("登录已失效，正在跳转登录页");
    }
    if (!response.ok) {
      let detail = body && body.detail ? body.detail : "";
      if (Array.isArray(detail)) {
        detail = detail.map((item) => item && item.msg ? item.msg : "").filter(Boolean).join("；");
      }
      if (!detail) detail = `请求失败 (${response.status})`;
      throw new Error(String(detail));
    }
    if (body === null) throw new Error("服务返回了无法解析的数据");
    return body;
  }

  function redirectToLogin() {
    const next = window.location.pathname + window.location.search;
    window.location.replace(`/login?next=${encodeURIComponent(next)}`);
  }

  async function loadCurrentUser() {
    try {
      const data = await apiJson("/api/auth/me");
      const user = data && data.user;
      if (!user || !user.username) return;
      const level = Math.max(0, Math.min(3, Number(user.vip_level) || 0));
      const chip = $("userName");
      if (chip) chip.textContent = user.username;
      const wrap = $("userChip");
      if (wrap) {
        wrap.title = `当前账户：${user.username} · ${VIP_NAMES[level]}`;
      }
      const welcome = $("welcome");
      if (welcome) welcome.dataset.vip = String(level);
      const welcomeText = $("welcomeText");
      if (welcomeText) {
        const prefix = level > 0 ? "尊贵的" : "";
        welcomeText.textContent = `欢迎回来，${prefix}${user.username}`;
      }
      const badge = $("vipBadge");
      if (badge) {
        if (level > 0) {
          badge.textContent = VIP_NAMES[level];
          badge.classList.remove("hidden");
        } else {
          badge.textContent = "";
          badge.classList.add("hidden");
        }
      }
      if (typeof user.is_simulated === "boolean") {
        state.isSimulated = user.is_simulated;
        updateSimulatedNotice();
      }
    } catch (error) {
      if (isAbortError(error)) return;
    }
  }

  function publicAiMessage(message) {
    return String(message || "")
      .replace(/DEEPSEEK_API_KEY/gi, "模型 API Key")
      .replace(/DeepSeek/gi, state.config.model || DISPLAY_MODEL);
  }

  function toast(message, kind = "info") {
    const element = $("toast");
    if (!element) return;
    element.textContent = message;
    element.classList.toggle("is-error", kind === "error");
    element.classList.add("is-visible");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => {
      element.classList.remove("is-visible");
    }, 3400);
  }

  function setAnalysisState(kind, text) {
    const chip = $("analysisState");
    chip.className = kind ? `status-chip is-${kind}` : "status-chip";
    $("analysisStateText").textContent = text;
    updateManualBuyButton();
  }

  function updateManualBuyButton() {
    const button = $("manualBuyBtn");
    if (!button) return;
    const ready =
      $("analysisStateText") &&
      $("analysisStateText").textContent === "研判完成" &&
      !state.detailSymbol;
    button.classList.toggle("hidden", !ready);
    button.disabled = !ready || state.manualBuyBusy;
    button.textContent = state.manualBuyBusy ? "提交中…" : "入手";
  }

  // -------------------------------------------------------------------------
  // Boot and configuration
  // -------------------------------------------------------------------------

  async function boot() {
    if (state.booted) return;
    state.booted = true;
    bindEvents();
    void loadCurrentUser();
    void loadAccountSummary();
    updateAutoTradeButton();
    startClock();
    updateMarketSession();
    window.setInterval(updateMarketSession, 30000);
    await initData();
  }

  async function initData() {
    setAnalysisState("running", "正在读取配置");
    const config = await loadConfig(state.platform);
    applyConfig(config);
    hydrateState();
    renderWatchlist();
    renderQueue();
    renderTabs();
    renderFocus();
    renderMetricsEmpty("等待行情");
    renderNewsEmpty("等待标的", "选择自选股后显示最近 30 天新闻。");
    updateWorkspaceMeta("选择标的开始，自动拉取两年行情并研判");
    updateActionStates();
    initAiWatch();
    initChart();

    if (!state.config.ai_configured) {
      renderAiConfigured();
    } else if (!state.selected.length) {
      renderAiNoSelection();
    }

    void fetchMarketQuotes(false);
    void fetchWatchQuotes(false);

    if (!state.selected.length) {
      setAnalysisState("idle", "等待选择");
      showChartOverlay("选择标的后显示走势");
      return;
    }

    setAnalysisState("running", "正在拉取行情");
    schedulePortfolioLoad({ delay: 80 });
  }

  function applyConfig(config) {
    state.config = config;
    state.maxSelection = Math.max(1, Math.min(12, Number(config.max_selection) || 5));
    renderPlatformChrome();
  }

  function renderPlatformChrome() {
    const config = state.config || fallbackConfig(state.platform);
    const appName = config.app_name || (state.platform === "HK" ? "J.T.C.G" : "J.T.C.A");
    const subtitle = config.subtitle || (state.platform === "HK" ? "港股量化分析工具" : "A股量化分析工具");
    const marketShort = config.market_short || (state.platform === "HK" ? "港股" : "A股");
    const model = config.model || DISPLAY_MODEL;
    const title = `${appName} ${subtitle}`;

    if ($("brandName")) $("brandName").textContent = appName;
    if ($("brandSub")) $("brandSub").textContent = subtitle;
    if ($("brandLink")) $("brandLink").setAttribute("aria-label", `${title}首页`);
    if ($("marketLabel")) $("marketLabel").textContent = config.market_label || `${marketShort}市场`;
    if ($("marketStrip")) $("marketStrip").setAttribute("aria-label", `${marketShort}市场指数`);
    if ($("modelName")) $("modelName").textContent = model;
    if ($("footBrand")) $("footBrand").textContent = title;
    if ($("stockSearch")) {
      $("stockSearch").placeholder = state.platform === "HK" ? "搜索港股代码或公司名" : "搜索 A 股代码或公司名";
    }
    document.title = title;
    const description = document.querySelector('meta[name="description"]');
    if (description) {
      description.setAttribute(
        "content",
        `${title}，基于东方财富行情、新闻与 ${model} 研判的股票研究面板。`,
      );
    }
    const buttons = document.querySelectorAll(".platform-btn");
    buttons.forEach((button) => {
      const active = button.dataset.platform === state.platform;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  async function loadConfig(platform = state.platform) {
    try {
      const data = await apiJson(`/api/config?platform=${encodeURIComponent(platform)}`);
      return { ...fallbackConfig(platform), ...data };
    } catch (error) {
      toast(error.message || "配置读取失败，已使用内置默认值", "error");
      return fallbackConfig(platform);
    }
  }

  function hydrateState() {
    const storedWatch = readStore(watchKey());
    const defaultWatch = sanitizeSymbolList(state.config.default_watchlist) || [];

    let watchlist = storedWatch !== null ? storedWatch : defaultWatch;
    watchlist = watchlist.slice(0, MAX_WATCHLIST);

    // 每次启动都等待用户手动勾选，不恢复上次的选择，也不自动触发研判。
    try {
      window.localStorage.removeItem(LEGACY_SELECTED_KEY);
    } catch (_error) {
      // 隐私模式下 localStorage 可能不可用，不影响本次选择。
    }

    state.watchlist = watchlist;
    state.selected = [];
    state.activeSymbol = null;
    persistState();
  }

  function abortPlatformRequests() {
    const controllers = [
      state.portfolioController,
      state.analysisController,
      state.quoteController,
      state.searchController,
      state.screenerController,
      state.liveController,
    ];
    controllers.forEach((controller) => {
      try {
        if (controller) controller.abort();
      } catch (_error) {
        // 已结束的请求可以忽略。
      }
    });
    state.intradayControllers.forEach((controller) => {
      try {
        controller.abort();
      } catch (_error) {
        // 已结束的请求可以忽略。
      }
    });
    state.intradayControllers.clear();
    state.portfolioController = null;
    state.analysisController = null;
    state.quoteController = null;
    state.searchController = null;
    state.screenerController = null;
    state.liveController = null;
    state.portfolioSeq += 1;
    state.analysisSeq += 1;
    state.quoteSeq += 1;
    state.marketSeq += 1;
    state.searchSeq += 1;
    state.screenerSeq += 1;
    state.liveSeq += 1;
  }

  function resetWorkspaceForPlatform() {
    window.clearTimeout(state.portfolioTimer);
    window.clearTimeout(state.searchTimer);
    window.clearTimeout(state.analysisTimer);
    state.portfolioTimer = null;
    state.searchTimer = null;
    state.analysisTimer = null;
    state.lastQuotes = new Map();
    state.bundles = new Map();
    state.liveQuotes = new Map();
    state.intraday = new Map();
    state.intradayErrors = new Map();
    state.intradayPending.clear();
    state.portfolio = null;
    state.analysisPayload = null;
    state.analysisStartedAt = 0;
    state.aiState = "idle";
    state.loadingPortfolio = false;
    state.searchResults = [];
    state.searchActive = -1;
    state.lastAllocation = null;
    state.screenerBusy = false;
    state.autoTradeBusy = false;
    state.manualBuyBusy = false;
    state.closePositionBusy = false;
    state.closePositionSymbol = null;
    state.sellMode = "full";
    state.sellShares = 0;
    state.detailSymbol = null;
  }

  function resetPlatformUi() {
    const search = $("stockSearch");
    if (search) search.value = "";
    closeSearch();
    const screenerResult = $("screenerResult");
    if (screenerResult) {
      screenerResult.classList.add("hidden");
      screenerResult.innerHTML = "";
    }
    const autoStatus = $("autoTradeStatus");
    if (autoStatus) autoStatus.classList.add("hidden");
    $("capitalInput").value = "10000";
    renderScreenerStatus(
      `${state.config.model || DISPLAY_MODEL} 将按资金筛选${state.config.market_short || "A股"}候选股票。`,
    );
    renderWatchlist();
    renderQueue();
    renderTabs();
    renderFocus();
    renderMetricsEmpty("等待行情");
    renderNewsEmpty("等待标的", "选择自选股后显示最近 30 天新闻。");
    updateWorkspaceMeta("选择标的开始，自动拉取两年行情并研判");
    updateActionStates();
    updateAutoTradeButton();
    updateManualBuyButton();
    if (state.chart) state.chart.clear();
    showChartOverlay("选择标的后显示走势");
    setAnalysisState("idle", "等待选择");
    if (!state.config.ai_configured) {
      renderAiConfigured();
    } else {
      renderAiNoSelection();
    }
  }

  async function switchPlatform(platform) {
    const next = platform === "HK" ? "HK" : "CN";
    if (next === state.platform) return;
    state.platform = next;
    persistPlatform();
    abortPlatformRequests();
    resetWorkspaceForPlatform();
    setAnalysisState("running", "正在切换平台");
    const config = await loadConfig(next);
    applyConfig(config);
    hydrateState();
    resetPlatformUi();
    updateMarketSession();
    void fetchMarketQuotes(true);
    void fetchWatchQuotes(true);
    void loadAccountSummary();
    toast(`已切换到 ${config.app_name} ${config.market_short || ""}平台`);
  }

  // -------------------------------------------------------------------------
  // Watchlist and selection
  // -------------------------------------------------------------------------

  function watchName(symbol) {
    const quote = state.lastQuotes.get(symbol);
    const bundle = state.bundles.get(symbol);
    return (bundle && bundle.name) || (quote && quote.name) || symbol;
  }

  function renderWatchlist() {
    const host = $("watchList");
    host.innerHTML = "";
    $("watchCount").textContent = String(state.watchlist.length).padStart(2, "0");

    if (!state.watchlist.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      const strong = document.createElement("strong");
      strong.textContent = "自选为空";
      const body = document.createElement("span");
      body.textContent = "用上方搜索添加股票代码。";
      empty.append(strong, body);
      host.appendChild(empty);
      return;
    }

    const fragment = document.createDocumentFragment();
    for (const symbol of state.watchlist) {
      const quote = state.lastQuotes.get(symbol);
      const selected = state.selected.includes(symbol);
      const row = document.createElement("div");
      row.className = `watch-row${selected ? " is-selected" : ""}`;
      row.dataset.symbol = symbol;
      row.setAttribute("role", "checkbox");
      row.setAttribute("aria-checked", String(selected));
      row.setAttribute("tabindex", "0");
      row.setAttribute("aria-label", `${symbol} ${watchName(symbol)}，${selected ? "已加入研判队列" : "未选择"}`);

      const check = document.createElement("span");
      check.className = "watch-check";
      check.textContent = "✓";
      check.setAttribute("aria-hidden", "true");

      const identity = document.createElement("span");
      identity.className = "watch-id";
      const symbolLine = document.createElement("span");
      symbolLine.className = "watch-symbol";
      symbolLine.textContent = symbol;
      const nameLine = document.createElement("span");
      nameLine.className = "watch-name";
      nameLine.textContent = watchName(symbol);
      identity.append(symbolLine, nameLine);

      const quoteBox = document.createElement("span");
      quoteBox.className = "watch-quote";
      const price = document.createElement("span");
      price.className = "watch-price";
      price.dataset.price = "1";
      price.textContent = quote ? formatPrice(quote.price) : "--";
      const pct = document.createElement("span");
      pct.className = "watch-pct";
      pct.dataset.pct = "1";
      if (quote) {
        pct.textContent = formatPercent(quote.change_pct);
        price.classList.add(toneClass(quote.change_pct));
        pct.classList.add(toneClass(quote.change_pct));
      } else {
        pct.textContent = "--";
      }
      quoteBox.append(price, pct);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "watch-remove";
      remove.dataset.action = "remove";
      remove.setAttribute("aria-label", `从自选移除 ${symbol}`);
      remove.title = "从自选移除";
      remove.appendChild(createIcon("x"));

      row.append(check, identity, quoteBox, remove);
      fragment.appendChild(row);
    }
    host.appendChild(fragment);
  }

  function updateWatchQuotes() {
    const rows = $("watchList").querySelectorAll(".watch-row");
    rows.forEach((row) => {
      const symbol = row.dataset.symbol;
      const quote = state.lastQuotes.get(symbol);
      const price = row.querySelector('[data-price="1"]');
      const pct = row.querySelector('[data-pct="1"]');
      if (!price || !pct) return;
      if (!quote) {
        price.textContent = "--";
        pct.textContent = "--";
        price.classList.remove("up", "down", "flat");
        pct.classList.remove("up", "down", "flat");
        return;
      }
      price.textContent = formatPrice(quote.price);
      pct.textContent = formatPercent(quote.change_pct);
      const tone = toneClass(quote.change_pct);
      for (const element of [price, pct]) {
        element.classList.remove("up", "down", "flat");
        element.classList.add(tone);
      }
    });
  }

  function renderQueue() {
    const host = $("queueChips");
    host.innerHTML = "";
    $("queueCount").textContent = `${state.selected.length}/${state.maxSelection}`;
    $("queueCount").classList.toggle("is-full", state.selected.length >= state.maxSelection);

    if (!state.selected.length) {
      const empty = document.createElement("span");
      empty.className = "queue-empty";
      empty.textContent = "尚未选择标的";
      host.appendChild(empty);
      updateActionStates();
      return;
    }

    const fragment = document.createDocumentFragment();
    for (const symbol of state.selected) {
      const chip = document.createElement("span");
      chip.className = "queue-chip";
      const label = document.createElement("span");
      label.textContent = symbol;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.dataset.symbol = symbol;
      remove.setAttribute("aria-label", `从研判队列移除 ${symbol}`);
      remove.title = "移除";
      remove.appendChild(createIcon("x"));
      chip.append(label, remove);
      fragment.appendChild(chip);
    }
    host.appendChild(fragment);
    updateActionStates();
  }

  function updateActionStates() {
    const aiBusy = state.aiState === "loading";
    const noSelection = state.selected.length === 0;
    const aiReady = Boolean(state.config.ai_configured);
    const detailMode = Boolean(state.detailSymbol);
    const analyzeBtn = $("analyzeBtn");
    const reanalyzeBtn = $("reanalyzeBtn");
    const refreshSelection = $("refreshSelection");

    analyzeBtn.disabled =
      detailMode || noSelection || !aiReady || aiBusy || state.loadingPortfolio || !state.portfolio;
    analyzeBtn.title = detailMode
      ? "持仓详情模式下请从自选清单发起研判"
      : !aiReady
        ? "未配置 AI 模型密钥"
        : noSelection
          ? "请先选择标的"
          : state.loadingPortfolio || !state.portfolio
            ? "行情尚未就绪"
            : aiBusy
              ? `${state.config.model || DISPLAY_MODEL} 正在研判`
              : "立即生成研判";
    analyzeBtn.innerHTML = `${ICON.spark}${aiBusy ? "研判中" : "立即研判"}`;

    reanalyzeBtn.disabled = detailMode || noSelection || !aiReady || aiBusy || !state.portfolio;
    reanalyzeBtn.title = detailMode ? "持仓详情模式下请从自选清单发起研判" : "";
    reanalyzeBtn.textContent = aiBusy ? "研判中" : "重新研判";
    refreshSelection.disabled = state.loadingPortfolio || (noSelection && !detailMode);
    updateScreenerButton();
    updateClosePositionButton();
  }

  function toggleSelection(symbol) {
    if (!state.watchlist.includes(symbol)) return;
    const index = state.selected.indexOf(symbol);
    if (index >= 0) {
      state.selected.splice(index, 1);
    } else if (state.selected.length >= state.maxSelection) {
      toast(`最多同时研判 ${state.maxSelection} 个标的`, "error");
      return;
    } else {
      state.selected.push(symbol);
    }
    persistState();
    renderWatchlist();
    renderQueue();
    selectionDidChange();
  }

  function removeWatchSymbol(symbol) {
    const wasSelected = state.selected.includes(symbol);
    state.watchlist = state.watchlist.filter((item) => item !== symbol);
    state.selected = state.selected.filter((item) => item !== symbol);
    if (state.activeSymbol === symbol) state.activeSymbol = state.selected[0] || null;
    persistState();
    renderWatchlist();
    renderQueue();
    if (wasSelected) {
      selectionDidChange();
    } else {
      updateActionStates();
    }
    scheduleWatchQuotes();
  }

  function addWatchSymbol(symbol, shouldSelect = true) {
    if (!state.watchlist.includes(symbol)) {
      if (state.watchlist.length >= MAX_WATCHLIST) {
        toast(`自选最多保留 ${MAX_WATCHLIST} 个代码`, "error");
        return false;
      }
      state.watchlist.push(symbol);
    }
    let selectionChanged = false;
    if (shouldSelect && !state.selected.includes(symbol)) {
      if (state.selected.length >= state.maxSelection) {
        toast(`已添加到自选，但研判队列已满 ${state.maxSelection} 个`, "error");
      } else {
        state.selected.push(symbol);
        state.activeSymbol = symbol;
        selectionChanged = true;
      }
    }
    persistState();
    renderWatchlist();
    renderQueue();
    scheduleWatchQuotes();
    if (selectionChanged) selectionDidChange();
    return true;
  }

  function selectionDidChange() {
    persistState();
    state.detailSymbol = null;
    clearIntradayData();
    state.portfolioSeq += 1;
    abortPortfolioRequest();
    abortAnalysisRequest();
    state.analysisSeq += 1;
    stopAnalysisTimer();
    state.analysisPayload = null;
    state.aiState = "idle";
    state.newsFilter = "all";
    state.newsLimit = 8;
    state.portfolio = null;
    state.bundles.clear();
    if (!state.activeSymbol || !state.selected.includes(state.activeSymbol)) {
      state.activeSymbol = state.selected[0] || null;
    }

    if (!state.selected.length) {
      resetWorkspace();
      return;
    }

    state.loadingPortfolio = true;
    setAnalysisState("running", "正在拉取行情");
    renderTabs();
    renderFocus();
    renderMetricsLoading();
    renderNewsLoading();
    renderDataTable(null);
    clearNotice();
    updateWorkspaceMeta(`正在同步 ${state.selected.join(" / ")} 的两年日线`);
    showChartOverlay("正在装载两年日线", true);
    renderAiPending(state.selected);
    updateActionStates();
    schedulePortfolioLoad({ delay: 320 });
  }

  function resetWorkspace() {
    state.detailSymbol = null;
    clearIntradayData();
    state.portfolioSeq += 1;
    state.analysisSeq += 1;
    abortPortfolioRequest();
    abortAnalysisRequest();
    stopAnalysisTimer();
    state.loadingPortfolio = false;
    state.portfolio = null;
    state.bundles.clear();
    state.activeSymbol = null;
    state.analysisPayload = null;
    state.aiState = "idle";
    state.newsFilter = "all";
    state.newsLimit = 8;
    setAnalysisState("idle", "等待选择");
    updateWorkspaceMeta("选择标的开始，自动拉取两年行情并研判");
    clearNotice();
    renderTabs();
    renderFocus();
    if (state.chart) state.chart.clear();
    showChartOverlay("选择标的后显示走势");
    renderMetricsEmpty("暂无数据");
    renderNewsEmpty("等待标的", "选择自选股后显示最近 30 天新闻。");
    renderDataTable(null);
    if (!state.config.ai_configured) {
      renderAiConfigured();
    } else {
      renderAiNoSelection();
    }
    updateActionStates();
  }

  // -------------------------------------------------------------------------
  // Auto screener
  // -------------------------------------------------------------------------

  function formatMoney(value) {
    const number = toFiniteNumber(value);
    if (number === null) return "--";
    return number.toLocaleString("zh-CN", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    });
  }

  function formatCurrency(value, { signed = false } = {}) {
    const number = toFiniteNumber(value);
    if (number === null) return "--";
    const prefix = signed && number > 0 ? "+" : "";
    return `${prefix}¥${number.toLocaleString("zh-CN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }

  function renderPositions(positions) {
    const list = $("positionList");
    const count = $("positionCount");
    const items = Array.isArray(positions) ? positions : [];
    if (count) count.textContent = String(items.length);
    if (!list) return;
    if (!items.length) {
      list.innerHTML = '<p class="position-empty">暂无持仓</p>';
      return;
    }
    list.innerHTML = items
      .map((item) => {
        const symbol = String(item.symbol || "");
        const name = item.name || symbol;
        const shares = Math.round(toFiniteNumber(item.shares) || 0);
        const price = toFiniteNumber(item.price) || 0;
        const buyPrice = toFiniteNumber(item.buy_price) || 0;
        const profit = toFiniteNumber(item.profit) || 0;
        const cost = buyPrice * shares;
        const pct = cost > 0 ? (profit / cost) * 100 : 0;
        const cls = profit > 0 ? "up" : profit < 0 ? "down" : "";
        const active = state.detailSymbol === symbol ? " is-active" : "";
        return `
          <div class="position-item${active}" data-symbol="${escapeHtml(symbol)}" data-name="${escapeHtml(name)}" role="button" tabindex="0" aria-label="查看 ${escapeHtml(name)} 详情">
            <div class="position-top">
              <span class="position-name">${escapeHtml(name)}</span>
              <span class="position-symbol">${escapeHtml(symbol)}</span>
            </div>
            <div class="position-line">
              <span>${shares.toLocaleString("zh-CN")} 股 · 现价 ¥${price.toFixed(2)}</span>
              <span class="position-value">市值 ${formatCurrency(item.market_value)}</span>
            </div>
            <div class="position-line">
              <span>成本 ¥${buyPrice.toFixed(2)}</span>
              <span class="position-profit ${cls}">${formatCurrency(profit, { signed: true })}（${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%）</span>
            </div>
          </div>`;
      })
      .join("");
  }

  function renderAccountSummary(summary) {
    if (!summary) return;
    state.accountSummary = summary;
    const balance = $("accountBalance");
    if (balance) balance.textContent = formatCurrency(summary.balance);
    const metrics = [
      ["holdingValue", summary.position_value, false],
      ["realtimeProfit", summary.realtime_profit, true],
      ["todayProfit", summary.today_profit, true],
      ["monthProfit", summary.month_profit, true],
      ["totalProfit", summary.total_profit, true],
    ];
    for (const [id, raw, signed] of metrics) {
      const element = $(id);
      if (!element) continue;
      const value = toFiniteNumber(raw) || 0;
      element.textContent = formatCurrency(value, { signed });
      element.classList.toggle("up", signed && value > 0);
      element.classList.toggle("down", signed && value < 0);
      element.title = formatCurrency(value, { signed });
    }
    if (typeof summary.is_simulated === "boolean") {
      state.isSimulated = summary.is_simulated;
    }
    renderPositions(summary.positions);
    updateSimulatedNotice();
    updateClosePositionButton();
  }

  function currentDetailPosition() {
    const symbol = state.detailSymbol;
    if (!symbol) return null;
    const positions = (state.accountSummary && state.accountSummary.positions) || [];
    return positions.find((item) => item.symbol === symbol) || null;
  }

  function updateClosePositionButton() {
    const wrap = $("positionActions");
    const button = $("closePositionBtn");
    if (!wrap || !button) return;
    const position = currentDetailPosition();
    const visible = Boolean(position);
    const shares = Math.max(0, Math.round(toFiniteNumber(position && position.shares) || 0));
    wrap.classList.toggle("hidden", !visible);
    button.disabled = !visible || state.closePositionBusy;
    button.title = visible
      ? `按最新价卖出 ${position.symbol} 的全部持仓`
      : "";
    button.innerHTML = state.closePositionBusy
      ? '<span class="loader" aria-hidden="true"></span>平仓中…'
      : `${ICON.x}一键平仓`;

    const input = $("partialSellShares");
    if (input) {
      const lot = Math.max(1, Math.round(toFiniteNumber(position && position.lot_size) || 100));
      input.step = String(lot);
      input.max = String(Math.floor(shares / lot) * lot);
      input.placeholder = `${lot} 的倍数`;
      input.title = `卖出股数需为 ${lot} 的整数倍`;
      input.disabled = !visible || state.closePositionBusy;
    }
    const partialBtn = $("partialSellBtn");
    if (partialBtn) partialBtn.disabled = !visible || state.closePositionBusy;
  }

  async function loadAccountSummary() {
    if (state.accountSummaryBusy) return;
    state.accountSummaryBusy = true;
    try {
      const data = await apiJson("/api/account/summary");
      renderAccountSummary(data);
    } catch (error) {
      if (isAbortError(error)) return;
      const list = $("positionList");
      if (list && !state.accountSummary) {
        list.innerHTML = '<p class="position-empty">持仓读取失败</p>';
      }
    } finally {
      state.accountSummaryBusy = false;
    }
  }

  function updateSimulatedNotice() {
    const notice = $("simulatedNotice");
    if (notice) notice.classList.toggle("hidden", !state.isSimulated);
    const type = $("accountType");
    if (type) type.textContent = state.isSimulated ? "模拟交易账号" : "真实交易账号";
  }

  function updateAutoTradeButton() {
    const button = $("autoTradeBtn");
    if (!button) return;
    const ready = Boolean(
      state.lastAllocation &&
        Array.isArray(state.lastAllocation.allocations) &&
        state.lastAllocation.allocations.length
    );
    button.disabled = !ready || state.autoTradeBusy;
    button.textContent = state.autoTradeBusy ? "交易提交中…" : "一键自动交易";
    button.title = state.autoTradeBusy
      ? "正在写入交易记录"
      : ready
        ? "按本次自动选股结果记录交易并开始模拟经营"
        : "自动选股完成后可交易";
  }

  function openContactModal(titleText) {
    const modal = $("contactModal");
    if (!modal) return;
    const title = $("contactTitle");
    if (title) title.textContent = titleText || "联系客服";
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    const close = $("contactClose");
    if (close) close.focus();
  }

  function closeContactModal() {
    const modal = $("contactModal");
    if (!modal || modal.classList.contains("hidden")) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }

  async function runAutoTrade() {
    if (state.autoTradeBusy) return;
    const allocation = state.lastAllocation;
    const items =
      allocation && Array.isArray(allocation.allocations)
        ? allocation.allocations
            .map((item) => ({
              symbol: item.symbol,
              shares: Number(item.shares),
            }))
            .filter(
              (item) =>
                item.symbol && Number.isFinite(item.shares) && item.shares > 0
            )
        : [];
    if (!items.length) {
      toast("请先完成自动选股", "error");
      return;
    }

    state.autoTradeBusy = true;
    updateAutoTradeButton();
    renderScreenerStatus("正在提交自动交易并写入账户…", {
      loading: true,
      hostId: "autoTradeStatus",
    });
    try {
      const data = await apiJson("/api/account/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          capital: allocation.capital,
          allocations: items,
        }),
      });
      const trade = data.trade || {};
      const count = Array.isArray(trade.positions)
        ? trade.positions.length
        : items.length;
      if (data.summary) renderAccountSummary(data.summary);
      else void loadAccountSummary();
      renderScreenerStatus(
        `交易已记录：${count} 只股票，成交金额 ${formatCurrency(trade.cost)}。模拟经营已开始，收益将按真实行情计算。`,
        { hostId: "autoTradeStatus" }
      );
      toast(`自动交易已记录，${count} 只股票已进入模拟经营`);
      state.lastAllocation = null;
    } catch (error) {
      if (isAbortError(error)) return;
      const message = publicAiMessage(
        error.message || "自动交易失败，请稍后重试"
      );
      renderScreenerStatus(message, {
        error: true,
        hostId: "autoTradeStatus",
      });
      toast(message, "error");
    } finally {
      state.autoTradeBusy = false;
      updateAutoTradeButton();
    }
  }

  function manualBuyEntries() {
    return [...state.selected].map((symbol) => {
      const bundle = state.bundles.get(symbol);
      const quote =
        (bundle && bundle.quote) ||
        state.lastQuotes.get(symbol) ||
        {};
      const price = toFiniteNumber(quote.price);
      return {
        symbol,
        name: (bundle && bundle.name) || quote.name || watchName(symbol),
        price,
        lot: symbolLotSize(symbol, 100),
      };
    });
  }

  function updateManualBuySummary() {
    const summary = $("manualBuySummary");
    const confirm = $("manualBuyConfirm");
    if (!summary) return;
    let total = 0;
    let count = 0;
    for (const row of document.querySelectorAll("#manualBuyList .buy-row")) {
      const input = row.querySelector(".buy-row-shares");
      const price = toFiniteNumber(row.dataset.price);
      const shares = Math.max(0, Math.round(Number(input && input.value) || 0));
      if (price && shares > 0) {
        total += price * shares;
        count += 1;
      }
    }
    const balance = toFiniteNumber(
      state.accountSummary && state.accountSummary.balance
    );
    const parts = [`本次买入 ${formatCurrency(total)}（${count} 只）`];
    if (balance !== null) {
      parts.push(`账户余额 ${formatCurrency(balance)}`);
      parts.push(`成交后剩余 ${formatCurrency(Math.max(0, balance - total))}`);
    }
    summary.textContent = total > 0 ? parts.join(" · ") : "填写股数后显示本次买入金额。";
    summary.classList.toggle("is-over", balance !== null && total > balance);
    if (confirm) confirm.disabled = state.manualBuyBusy || total <= 0;
  }

  function openManualBuyModal() {
    if (state.manualBuyBusy) return;
    const entries = manualBuyEntries();
    if (!entries.length) {
      toast("请先勾选自选股", "error");
      return;
    }
    const list = $("manualBuyList");
    if (!list) return;
    list.innerHTML = entries
      .map((item) => {
        const priceText =
          item.price !== null ? formatCurrency(item.price) : "价格暂缺";
        const lot = Math.max(1, Math.round(Number(item.lot) || 100));
        const lotText =
          item.price !== null
            ? `一手 ${formatCurrency(item.price * lot)}（${lot} 股）`
            : `每手 ${lot} 股`;
        return `
          <label class="buy-row${item.price === null ? " is-disabled" : ""}" data-symbol="${escapeHtml(item.symbol)}" data-price="${item.price === null ? "" : item.price}" data-lot="${lot}">
            <span class="buy-row-id">
              <span class="buy-row-name">${escapeHtml(item.name)}</span>
              <span class="buy-row-code">${escapeHtml(item.symbol)}</span>
            </span>
            <span class="buy-row-price">${escapeHtml(priceText)}<small>${escapeHtml(lotText)}</small></span>
            <input class="buy-row-shares" type="number" min="0" step="${lot}" value="0" inputmode="numeric" aria-label="买入 ${escapeHtml(item.name)} 的股数" ${item.price === null ? "disabled" : ""}>
          </label>`;
      })
      .join("");
    const hint = $("manualBuyHint");
    const balance = toFiniteNumber(
      state.accountSummary && state.accountSummary.balance
    );
    if (hint) {
      const lotNote = state.config.lot_note || (state.platform === "HK" ? "港股每手股数因股票而异" : "A 股按手交易（100 股为一手）");
      hint.textContent =
        balance !== null
          ? `选择要买入的自选股并填写股数，${lotNote}。当前可用余额 ${formatCurrency(balance)}。`
          : `选择要买入的自选股并填写股数，${lotNote}。`;
    }
    updateManualBuySummary();
    const modal = $("manualBuyModal");
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    const firstInput = list.querySelector(".buy-row-shares:not(:disabled)");
    if (firstInput) firstInput.focus();
  }

  function closeManualBuyModal() {
    const modal = $("manualBuyModal");
    if (!modal || modal.classList.contains("hidden") || state.manualBuyBusy) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }

  async function confirmManualBuy() {
    if (state.manualBuyBusy) return;
    const items = [];
    for (const row of document.querySelectorAll("#manualBuyList .buy-row")) {
      const input = row.querySelector(".buy-row-shares");
      if (!input || input.disabled) continue;
      const shares = Math.round(Number(input.value) || 0);
      if (shares <= 0) continue;
      const price = toFiniteNumber(row.dataset.price);
      const lot = Math.max(1, Math.round(toFiniteNumber(row.dataset.lot) || 100));
      if (shares % lot !== 0) {
        toast(`买入股数需为 ${lot} 的整数倍（每手 ${lot} 股）`, "error");
        input.focus();
        return;
      }
      items.push({ symbol: row.dataset.symbol, shares, price });
    }
    if (!items.length) {
      toast("请至少填写一只股票的买入股数", "error");
      return;
    }
    const total = items.reduce(
      (sum, item) => sum + (item.price || 0) * item.shares,
      0
    );
    const balance = toFiniteNumber(
      state.accountSummary && state.accountSummary.balance
    );
    if (balance !== null && total > balance + 0.001) {
      toast(
        `账户余额不足：需要 ${formatCurrency(total)}，当前余额 ${formatCurrency(balance)}`,
        "error"
      );
      return;
    }

    state.manualBuyBusy = true;
    const confirm = $("manualBuyConfirm");
    const cancel = $("manualBuyCancel");
    if (confirm) {
      confirm.disabled = true;
      confirm.textContent = "提交中…";
    }
    if (cancel) cancel.disabled = true;
    try {
      const data = await apiJson("/api/account/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          capital: Math.round(total * 100) / 100,
          allocations: items.map((item) => ({
            symbol: item.symbol,
            shares: item.shares,
          })),
        }),
      });
      const trade = data.trade || {};
      const count = Array.isArray(trade.positions)
        ? trade.positions.length
        : items.length;
      if (data.summary) renderAccountSummary(data.summary);
      else void loadAccountSummary();
      state.manualBuyBusy = false;
      closeManualBuyModal();
      toast(
        `已入手 ${count} 只股票，成交金额 ${formatCurrency(trade.cost)}，持仓已开始按真实行情计算`
      );
    } catch (error) {
      if (isAbortError(error)) return;
      toast(publicAiMessage(error.message || "入手失败，请稍后重试"), "error");
    } finally {
      state.manualBuyBusy = false;
      if (confirm) {
        confirm.disabled = false;
        confirm.textContent = "确认入手";
      }
      if (cancel) cancel.disabled = false;
      updateManualBuySummary();
      updateManualBuyButton();
    }
  }

  function openSellModal(mode, shares) {
    const position = currentDetailPosition();
    if (!position) {
      toast("当前没有该股票的持仓", "error");
      return;
    }
    const symbol = position.symbol;
    const total = Math.max(0, Math.round(toFiniteNumber(position.shares) || 0));
    if (total <= 0) {
      toast("当前没有可卖出的持仓", "error");
      return;
    }
    const qty = Math.max(0, Math.min(total, Math.round(Number(shares) || 0)));
    const full = mode === "full" || qty >= total;
    const label = position.name || symbol;
    state.closePositionSymbol = symbol;
    state.sellMode = full ? "full" : "partial";
    state.sellShares = full ? total : qty;
    $("closePositionTitle").textContent = full
      ? `一键平仓 · ${label}`
      : `部分卖出 · ${label}`;
    $("closePositionText").textContent = full
      ? `将按最新价卖出 ${label}（${symbol}）的全部 ${total.toLocaleString("zh-CN")} 股，成交后资金回到账户余额。确定继续吗？`
      : `将按最新价卖出 ${label}（${symbol}）${qty.toLocaleString("zh-CN")} 股，剩余 ${(total - qty).toLocaleString("zh-CN")} 股，成交后资金回到账户余额。确定继续吗？`;
    $("closePositionConfirm").textContent = full ? "确认平仓" : "确认卖出";
    const modal = $("closePositionModal");
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    $("closePositionCancel").focus();
  }

  function openClosePositionModal() {
    if (state.closePositionBusy) return;
    openSellModal("full", 0);
  }

  function openPartialSellModal() {
    if (state.closePositionBusy) return;
    const position = currentDetailPosition();
    if (!position) {
      toast("当前没有该股票的持仓", "error");
      return;
    }
    const total = Math.max(0, Math.round(toFiniteNumber(position.shares) || 0));
    const lot = Math.max(1, Math.round(toFiniteNumber(position.lot_size) || 100));
    if (total < lot) {
      toast("剩余持仓不足一手，请使用一键平仓", "error");
      return;
    }
    const input = $("partialSellShares");
    const qty = Math.floor(Number(input ? input.value : ""));
    if (!Number.isFinite(qty) || qty <= 0) {
      toast("请输入要卖出的股数", "error");
      if (input) input.focus();
      return;
    }
    if (qty > total) {
      toast(`最多可卖出 ${total.toLocaleString("zh-CN")} 股`, "error");
      if (input) input.focus();
      return;
    }
    if (qty < total && qty % lot !== 0) {
      toast(`卖出股数需为 ${lot} 的整数倍（每手 ${lot} 股）`, "error");
      if (input) input.focus();
      return;
    }
    openSellModal(qty >= total ? "full" : "partial", qty);
  }

  function closeClosePositionModal() {
    const modal = $("closePositionModal");
    if (!modal || modal.classList.contains("hidden")) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    if (!state.closePositionBusy) state.closePositionSymbol = null;
  }

  async function confirmClosePosition() {
    const symbol = state.closePositionSymbol;
    if (!symbol || state.closePositionBusy) return;
    const partial = state.sellMode === "partial";
    const sellShares = Math.max(0, Math.round(Number(state.sellShares) || 0));
    if (partial && sellShares <= 0) {
      toast("请输入要卖出的股数", "error");
      return;
    }
    state.closePositionBusy = true;
    $("closePositionConfirm").disabled = true;
    $("closePositionCancel").disabled = true;
    updateClosePositionButton();
    try {
      const data = await apiJson(
        partial ? "/api/account/sell-position" : "/api/account/close-position",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(partial ? { symbol, shares: sellShares } : { symbol }),
        }
      );
      const closed = data.sold || data.closed || {};
      const shares = Math.round(toFiniteNumber(closed.shares) || 0);
      const remaining = Math.round(toFiniteNumber(closed.remaining_shares) || 0);
      const realized = toFiniteNumber(closed.realized);
      const realizedText =
        realized === null
          ? ""
          : `，本次收益 ${formatCurrency(realized, { signed: true })}`;
      const name = closed.name || symbol;
      state.closePositionSymbol = null;
      closeClosePositionModal();
      const input = $("partialSellShares");
      if (input) input.value = "";
      if (data.summary) renderAccountSummary(data.summary);
      else void loadAccountSummary();
      toast(
        remaining > 0
          ? `已卖出 ${name} ${shares.toLocaleString("zh-CN")} 股，剩余 ${remaining.toLocaleString("zh-CN")} 股，成交金额 ${formatCurrency(closed.proceeds)}${realizedText}`
          : `已平仓 ${name} ${shares.toLocaleString("zh-CN")} 股，成交金额 ${formatCurrency(closed.proceeds)}${realizedText}`
      );
    } catch (error) {
      if (isAbortError(error)) return;
      toast(error.message || "卖出失败，请稍后重试", "error");
    } finally {
      state.closePositionBusy = false;
      $("closePositionConfirm").disabled = false;
      $("closePositionCancel").disabled = false;
      updateActionStates();
    }
  }

  // -------------------------------------------------------------------------
  // AI monitoring
  // -------------------------------------------------------------------------

  function aiWatchStrategyLabel(score) {
    const value = Math.max(0, Math.min(100, Math.round(Number(score) || 0)));
    if (value <= 33) return "防御";
    if (value <= 66) return "均衡";
    return "激进";
  }

  function loadAiWatchSettings() {
    try {
      const raw = window.localStorage.getItem(AIWATCH_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return;
      state.aiWatchEnabled = parsed.enabled === true;
      const score = Math.round(Number(parsed.strategy));
      state.aiWatchStrategy = Number.isFinite(score)
        ? Math.max(0, Math.min(100, score))
        : 50;
    } catch (_error) {
      // Ignore malformed or unavailable local storage.
    }
  }

  function persistAiWatchSettings() {
    try {
      window.localStorage.setItem(
        AIWATCH_KEY,
        JSON.stringify({
          enabled: state.aiWatchEnabled,
          strategy: state.aiWatchStrategy,
        })
      );
    } catch (_error) {
      // Local storage can be unavailable in private mode.
    }
  }

  function updateAiWatchUi() {
    const enabled = state.aiWatchEnabled;
    const aiReady = Boolean(state.config.ai_configured);
    const badge = $("aiWatchBadge");
    if (badge) {
      badge.textContent = state.aiWatchBusy
        ? "分析中"
        : enabled
          ? "运行中"
          : "关闭";
      badge.classList.toggle("is-on", enabled && !state.aiWatchBusy);
    }
    const toggle = $("aiWatchSwitch");
    if (toggle) {
      toggle.checked = enabled;
      toggle.disabled = !aiReady;
      toggle.title = aiReady ? "" : "智能盯盘服务暂不可用";
    }
    const slider = $("aiWatchStrategy");
    if (slider) {
      slider.value = String(state.aiWatchStrategy);
      slider.disabled = !aiReady;
    }
    const label = $("aiWatchStrategyLabel");
    if (label) label.textContent = aiWatchStrategyLabel(state.aiWatchStrategy);
  }

  function renderAiWatchStatus(message, { loading = false, error = false } = {}) {
    const host = $("aiWatchStatus");
    if (!host) return;
    host.classList.toggle("hidden", !message);
    host.classList.toggle("is-loading", Boolean(message) && loading);
    host.classList.toggle("is-error", Boolean(message) && error);
    host.textContent = message || "";
  }

  function renderAiWatchResult(data) {
    const host = $("aiWatchResult");
    if (!host) return;
    state.aiWatchResult = data || null;
    const positions = Array.isArray(data && data.positions) ? data.positions : [];
    const summary =
      (data && data.summary) || "本次未发现需要调整的持仓，维持当前仓位。";
    host.classList.remove("hidden");
    if (!positions.length) {
      host.innerHTML = `<p class="ai-watch-summary">${escapeHtml(summary)}</p>`;
      return;
    }
    const actionable = positions.filter((item) => item.action !== "持有").length;
    const executed = Array.isArray(data && data.executed) ? data.executed : [];
    const cards = positions
      .map((item) => {
        const action = item.action || "持有";
        const cls =
          action === "全部平仓" ? "is-close" : action === "部分抛出" ? "is-trim" : "is-hold";
        const shares = Math.max(
          0,
          Math.round(toFiniteNumber(item.shares) || 0)
        );
        const sellShares = Math.max(
          0,
          Math.round(toFiniteNumber(item.sell_shares) || 0)
        );
        const ratio = toFiniteNumber(item.sell_ratio) || 0;
        let detail;
        if (action === "全部平仓") {
          detail = `建议卖出全部 ${shares.toLocaleString("zh-CN")} 股`;
        } else if (action === "部分抛出") {
          detail = `建议卖出 ${sellShares.toLocaleString("zh-CN")} 股（${ratio}%）`;
        } else {
          detail = `继续持有 ${shares.toLocaleString("zh-CN")} 股`;
        }
        return `
          <article class="ai-watch-card ${cls}">
            <div class="ai-watch-card-top">
              <span class="ai-watch-card-name">${escapeHtml(item.name || item.symbol)}</span>
              <span class="ai-watch-action ${cls}">${escapeHtml(action)}</span>
            </div>
            <span class="ai-watch-card-symbol">${escapeHtml(item.symbol || "")}</span>
            <p class="ai-watch-card-detail">${escapeHtml(detail)}</p>
            <p class="ai-watch-card-reason">${escapeHtml(item.reason || "")}</p>
          </article>`;
      })
      .join("");
    const executedText = executed.length
      ? `本次已自动卖出：${executed
          .map(
            (item) =>
              `${item.name || item.symbol} ${Number(item.shares || 0).toLocaleString("zh-CN")} 股`
          )
          .join("；")}`
      : data && data.auto_execute
        ? "AI 盯盘已开启，满足条件的持仓会自动卖出。"
        : "结论仅供参考，交易需手动确认。";
    host.innerHTML = `
      <div class="ai-watch-result-head">
        <span>${escapeHtml((data && data.strategy_label) || aiWatchStrategyLabel(state.aiWatchStrategy))}策略</span>
        <span>${actionable ? `${actionable} 只建议调整` : "无需操作"}</span>
      </div>
      <p class="ai-watch-summary">${escapeHtml(summary)}</p>
      <div class="ai-watch-cards">${cards}</div>
      <p class="ai-watch-foot">${escapeHtml(executedText)}</p>`;
  }

  function aiWatchRunningMessage(data, prefix) {
    const lastRun = data && data.last_run_at ? formatLocalTime(data.last_run_at) : null;
    const nextRun = data && data.next_run_at ? formatLocalTime(data.next_run_at) : null;
    const parts = [prefix];
    if (lastRun) parts.push(`上次 ${lastRun}`);
    if (nextRun) parts.push(`下次约 ${nextRun}`);
    return parts.join(" · ");
  }

  function applyAiWatchStatus(data) {
    if (!data || typeof data !== "object") return;
    if (data.enabled !== undefined) {
      state.aiWatchEnabled = Boolean(data.enabled);
    }
    const score = Math.round(Number(data.strategy));
    if (Number.isFinite(score)) {
      state.aiWatchStrategy = Math.max(0, Math.min(100, score));
    }
    persistAiWatchSettings();
    updateAiWatchUi();
    if (data.last_result) {
      renderAiWatchResult(data.last_result);
    }
    if (state.aiWatchEnabled) {
      if (data.last_error) {
        renderAiWatchStatus(data.last_error, { error: true });
      } else {
        renderAiWatchStatus(
          aiWatchRunningMessage(data, "后端盯盘运行中，每 30 分钟自动评估并抛售")
        );
      }
    } else {
      renderAiWatchStatus("AI 盯盘已关闭，保留上次结论");
    }
    if (state.aiWatchEnabled && state.config.ai_configured) {
      startAiWatchTimer();
    } else {
      stopAiWatchTimer();
    }
  }

  async function syncAiWatchStatus() {
    try {
      const data = await apiJson("/api/account/ai-watch");
      applyAiWatchStatus(data);
    } catch (error) {
      if (isAbortError(error)) return;
      renderAiWatchStatus(
        publicAiMessage(error.message || "AI 盯盘状态读取失败"),
        { error: true }
      );
    }
  }

  function stopAiWatchTimer() {
    if (state.aiWatchTimer) {
      window.clearInterval(state.aiWatchTimer);
      state.aiWatchTimer = null;
    }
  }

  function startAiWatchTimer() {
    stopAiWatchTimer();
    state.aiWatchTimer = window.setInterval(() => {
      if (document.hidden || !state.aiWatchEnabled) return;
      void syncAiWatchStatus();
    }, AIWATCH_POLL_MS);
  }

  async function setAiWatchEnabled(enabled) {
    if (state.aiWatchBusy) return;
    const target = Boolean(enabled);
    const previous = state.aiWatchEnabled;
    state.aiWatchBusy = true;
    updateAiWatchUi();
    renderAiWatchStatus(
      target ? "正在启动后台盯盘并执行首次评估…" : "正在关闭 AI 盯盘…",
      { loading: target }
    );
    try {
      const data = await apiJson("/api/account/ai-watch/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: target,
          strategy: state.aiWatchStrategy,
        }),
      });
      state.aiWatchEnabled = target;
      applyAiWatchStatus(data.status || { enabled: target, strategy: state.aiWatchStrategy });
      if (data.result) {
        renderAiWatchResult(data.result);
      }
      if (data.error) {
        toast(publicAiMessage(data.error), "error");
      } else if (target) {
        const sold = Array.isArray(data.result && data.result.executed)
          ? data.result.executed.length
          : 0;
        toast(sold ? `AI 盯盘已开启，本次自动卖出 ${sold} 笔` : "AI 盯盘已开启，后端每 30 分钟自动评估并抛售");
      } else {
        toast("AI 盯盘已关闭，后台不再自动评估");
      }
    } catch (error) {
      if (isAbortError(error)) return;
      state.aiWatchEnabled = previous;
      updateAiWatchUi();
      const message = publicAiMessage(
        error.message || (target ? "AI 盯盘启动失败" : "AI 盯盘关闭失败")
      );
      renderAiWatchStatus(message, { error: true });
      toast(message, "error");
    } finally {
      state.aiWatchBusy = false;
      updateAiWatchUi();
    }
  }

  async function initAiWatch() {
    loadAiWatchSettings();
    updateAiWatchUi();
    if (!state.config.ai_configured) {
      state.aiWatchEnabled = false;
      stopAiWatchTimer();
      updateAiWatchUi();
      renderAiWatchStatus("智能盯盘服务暂不可用");
      return;
    }
    try {
      const data = await apiJson("/api/account/ai-watch");
      applyAiWatchStatus(data);
    } catch (error) {
      if (isAbortError(error)) return;
      state.aiWatchEnabled = false;
      stopAiWatchTimer();
      updateAiWatchUi();
      renderAiWatchStatus(
        publicAiMessage(error.message || "AI 盯盘状态读取失败"),
        { error: true }
      );
    }
  }

  function updateScreenerButton() {
    const button = $("screenBtn");
    if (!button) return;
    const aiReady = Boolean(state.config.ai_configured);
    button.disabled = state.screenerBusy || !aiReady;
    button.title = !aiReady
      ? "未配置 AI 模型密钥"
      : state.screenerBusy
        ? "自动选股进行中"
        : "按资金自动筛选并配置";
    button.innerHTML = `${ICON.spark}${state.screenerBusy ? "筛选中" : "自动选股"}`;
  }

  function setScreenerBusy(busy) {
    state.screenerBusy = busy;
    $("capitalInput").disabled = busy;
    updateScreenerButton();
  }

  function renderScreenerStatus(
    message,
    { loading = false, error = false, hostId = "screenerStatus" } = {}
  ) {
    const host = $(hostId);
    if (!host) return;
    host.classList.remove("hidden");
    host.classList.toggle("is-error", error);
    host.innerHTML = "";
    if (loading) {
      const spinner = document.createElement("span");
      spinner.className = "loader";
      spinner.setAttribute("aria-hidden", "true");
      host.appendChild(spinner);
    }
    const text = document.createElement("span");
    text.textContent = message;
    host.appendChild(text);
  }

  function renderScreenerCandidates(screen) {
    const host = $("screenerResult");
    host.classList.remove("hidden");
    host.innerHTML = "";
    const summary = document.createElement("p");
    summary.className = "screener-summary";
    summary.textContent = `候选 ${screen.candidates.length} 只${screen.note ? ` · ${screen.note}` : ""}`;
    const chips = document.createElement("div");
    chips.className = "screener-candidates";
    for (const item of screen.candidates) {
      const chip = document.createElement("span");
      chip.className = "screener-candidate";
      chip.textContent = `${item.symbol} ${item.name || ""}`.trim();
      if (item.reason) chip.title = item.reason;
      chips.appendChild(chip);
    }
    host.append(summary, chips);
  }

  function renderScreenerResult(result) {
    const host = $("screenerResult");
    host.classList.remove("hidden");
    host.innerHTML = "";
    const allocations = Array.isArray(result.allocations) ? result.allocations : [];

    const summary = document.createElement("p");
    summary.className = "screener-summary";
    summary.textContent = result.summary || "模型未提供配置说明。";
    host.appendChild(summary);

    const tags = document.createElement("div");
    tags.className = "screener-tags";
    const entries = [
      `投入 ¥${formatMoney(result.invested)}`,
      `现金 ¥${formatMoney(result.unallocated_cash)}`,
      result.risk_level ? `风格 ${result.risk_level}` : "",
    ].filter(Boolean);
    for (const entry of entries) {
      const tag = document.createElement("span");
      tag.className = "screener-tag";
      tag.textContent = entry;
      tags.appendChild(tag);
    }
    host.appendChild(tags);

    for (const item of allocations) {
      const row = document.createElement("div");
      row.className = "screener-pick";
      row.dataset.symbol = item.symbol;
      row.setAttribute("role", "button");
      row.setAttribute("tabindex", "0");

      const top = document.createElement("div");
      top.className = "screener-pick-top";
      const symbol = document.createElement("span");
      symbol.className = "screener-pick-symbol";
      symbol.textContent = item.symbol;
      const name = document.createElement("span");
      name.className = "screener-pick-name";
      name.textContent = item.name || "";
      const weight = document.createElement("span");
      weight.className = "screener-pick-weight";
      weight.textContent = formatPercent(item.actual_weight, false);
      top.append(symbol, name, weight);

      const meta = document.createElement("div");
      meta.className = "screener-pick-meta";
      meta.textContent = `¥${formatMoney(item.amount)} · ${item.shares} 股 · ${item.role || "配置"}`;

      row.append(top, meta);
      if (item.reason) {
        const reason = document.createElement("p");
        reason.className = "screener-pick-reason";
        reason.textContent = item.reason;
        row.appendChild(reason);
      }
      host.appendChild(row);
    }
  }

  function applyAutoSelection(symbols) {
    const picked = (sanitizeSymbolList(symbols) || []).slice(0, state.maxSelection);
    if (!picked.length) return;
    const rest = state.watchlist.filter((symbol) => !picked.includes(symbol));
    state.watchlist = [...picked, ...rest].slice(0, MAX_WATCHLIST);
    state.selected = picked;
    state.activeSymbol = picked[0];
    persistState();
    renderWatchlist();
    renderQueue();
    selectionDidChange();
    void fetchWatchQuotes(false);
    toast(`已载入 ${picked.join("、")} 到组合情报`);
  }

  async function runScreener() {
    if (state.screenerBusy) return;
    if (!state.config.ai_configured) {
      toast("未配置模型密钥，无法自动选股", "error");
      return;
    }
    const capital = Number($("capitalInput").value);
    if (!Number.isFinite(capital) || capital < 200) {
      toast("请输入至少 200 元的入股资金", "error");
      $("capitalInput").focus();
      return;
    }

    const seq = ++state.screenerSeq;
    if (state.screenerController) state.screenerController.abort();
    const controller = new AbortController();
    state.screenerController = controller;
    setScreenerBusy(true);
    state.lastAllocation = null;
    updateAutoTradeButton();
    $("autoTradeStatus").classList.add("hidden");
    $("screenerResult").classList.add("hidden");
    $("screenerResult").innerHTML = "";
    renderScreenerStatus(`${state.config.model || DISPLAY_MODEL} 正在按资金筛选候选股票…`, {
      loading: true,
    });

    try {
      const screen = await apiJson("/api/screen/candidates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capital, count: 8, platform: state.platform }),
        signal: controller.signal,
      });
      if (seq !== state.screenerSeq) return;
      const candidates = Array.isArray(screen.candidates) ? screen.candidates : [];
      if (!candidates.length) throw new Error("模型未返回有效候选股票");
      renderScreenerCandidates(screen);
      renderScreenerStatus(
        `已选出 ${candidates.length} 只候选，正在拉取近一月行情与舆情并优化配置…`,
        { loading: true },
      );

      const result = await apiJson("/api/screen/optimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          capital,
          candidates: candidates.map((item) => item.symbol),
          platform: state.platform,
        }),
        signal: controller.signal,
      });
      if (seq !== state.screenerSeq) return;
      state.screenerController = null;
      const allocations = Array.isArray(result.allocations) ? result.allocations : [];
      if (!allocations.length) throw new Error("模型未返回有效配置");
      setScreenerBusy(false);
      renderScreenerResult(result);
      state.lastAllocation = { capital, allocations };
      updateAutoTradeButton();
      renderScreenerStatus(
        `配置完成：${allocations.length} 只股票，投入 ¥${formatMoney(result.invested)}，现金 ¥${formatMoney(result.unallocated_cash)}。可点击下方“一键自动交易”记录本次配置。`,
      );
      applyAutoSelection(allocations.map((item) => item.symbol));
    } catch (error) {
      if (isAbortError(error)) return;
      if (seq !== state.screenerSeq) return;
      state.screenerController = null;
      setScreenerBusy(false);
      const message = publicAiMessage(error.message || "自动选股失败，请稍后重试");
      renderScreenerStatus(message, { error: true });
      toast(message, "error");
    }
  }

  // -------------------------------------------------------------------------
  // Search
  // -------------------------------------------------------------------------

  function bindSearch() {
    const input = $("stockSearch");
    input.addEventListener("input", () => {
      const query = input.value.trim();
      window.clearTimeout(state.searchTimer);
      if (!query) {
        closeSearch();
        return;
      }
      state.searchTimer = window.setTimeout(() => {
        void runSearch(query);
      }, 180);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (!state.searchResults.length) return;
        event.preventDefault();
        const direction = event.key === "ArrowDown" ? 1 : -1;
        const count = state.searchResults.length;
        state.searchActive = (state.searchActive + direction + count) % count;
        paintSearchActive();
        return;
      }
      if (event.key === "Enter") {
        if (state.searchResults.length) {
          event.preventDefault();
          const index = state.searchActive >= 0 ? state.searchActive : 0;
          const result = state.searchResults[index];
          if (result) pickSearchResult(result.symbol);
        }
        return;
      }
      if (event.key === "Escape") {
        closeSearch();
        input.blur();
      }
    });

    document.addEventListener("click", (event) => {
      if (!$("searchBox").contains(event.target)) closeSearch();
    });
  }

  async function runSearch(query) {
    const seq = ++state.searchSeq;
    if (state.searchController) state.searchController.abort();
    const controller = new AbortController();
    state.searchController = controller;
    try {
      const data = await apiJson(`/api/search?q=${encodeURIComponent(query)}&${platformParam()}`, {
        signal: controller.signal,
      });
      if (seq !== state.searchSeq) return;
      state.searchResults = Array.isArray(data.results) ? data.results : [];
      state.searchActive = state.searchResults.length ? 0 : -1;
      renderSearchResults();
    } catch (error) {
      if (isAbortError(error)) return;
      if (seq !== state.searchSeq) return;
      state.searchResults = [];
      state.searchActive = -1;
      const host = $("searchResults");
      host.innerHTML = "";
      const empty = document.createElement("div");
      empty.className = "search-empty";
      empty.textContent = "搜索暂不可用，可直接输入代码后回车重试。";
      host.appendChild(empty);
      host.classList.remove("hidden");
    }
  }

  function renderSearchResults() {
    const host = $("searchResults");
    host.innerHTML = "";
    if (!state.searchResults.length) {
      const empty = document.createElement("div");
      empty.className = "search-empty";
      empty.textContent = "没有找到匹配的标的。";
      host.appendChild(empty);
      host.classList.remove("hidden");
      return;
    }

    state.searchResults.forEach((result, index) => {
      const symbol = String(result.symbol || "").toUpperCase();
      const inWatch = state.watchlist.includes(symbol);
      const inQueue = state.selected.includes(symbol);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `search-result${index === state.searchActive ? " is-active" : ""}`;
      button.dataset.symbol = symbol;
      button.dataset.index = String(index);
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(index === state.searchActive));

      const main = document.createElement("span");
      main.className = "search-result-main";
      const symbolLine = document.createElement("span");
      symbolLine.className = "search-result-symbol";
      symbolLine.textContent = symbol;
      const nameLine = document.createElement("span");
      nameLine.className = "search-result-name";
      const parts = [result.name || symbol];
      if (result.cn) parts.push(result.cn);
      if (result.exchange) parts.push(result.exchange);
      nameLine.textContent = parts.join(" · ");
      main.append(symbolLine, nameLine);

      const action = document.createElement("span");
      action.className = "search-result-add";
      action.textContent = inQueue ? "已选择" : inWatch ? "选择" : "添加";
      button.append(main, action);
      button.addEventListener("click", () => pickSearchResult(symbol));
      host.appendChild(button);
    });
    host.classList.remove("hidden");
  }

  function paintSearchActive() {
    const host = $("searchResults");
    host.querySelectorAll(".search-result").forEach((button, index) => {
      button.classList.toggle("is-active", index === state.searchActive);
      button.setAttribute("aria-selected", String(index === state.searchActive));
      if (index === state.searchActive) {
        button.scrollIntoView({ block: "nearest" });
      }
    });
  }

  function pickSearchResult(symbol) {
    if (!symbol) return;
    if (state.watchlist.includes(symbol) && state.selected.includes(symbol)) {
      toast(`${symbol} 已在研判队列`);
    } else if (!addWatchSymbol(symbol, true)) {
      return;
    }
    $("stockSearch").value = "";
    closeSearch();
    $("stockSearch").blur();
  }

  function closeSearch() {
    $("searchResults").classList.add("hidden");
    state.searchResults = [];
    state.searchActive = -1;
  }

  function scheduleWatchQuotes() {
    window.clearTimeout(state.watchQuoteTimer);
    state.watchQuoteTimer = window.setTimeout(() => {
      void fetchWatchQuotes(false);
    }, 220);
  }

  // -------------------------------------------------------------------------
  // Quotes and market strip
  // -------------------------------------------------------------------------

  async function fetchMarketQuotes(force = false) {
    const seq = ++state.marketSeq;
    try {
      const data = await apiJson(`/api/market?refresh=${force ? "1" : "0"}&${platformParam()}`);
      if (seq !== state.marketSeq) return;
      renderMarket(data);
    } catch (error) {
      if (seq !== state.marketSeq) return;
      renderMarketError();
    }
  }

  async function fetchWatchQuotes(force = false) {
    if (!state.watchlist.length) {
      state.quoteSeq += 1;
      if (state.quoteController) {
        state.quoteController.abort();
        state.quoteController = null;
      }
      state.lastQuotes.clear();
      updateSourceIndicator();
      return;
    }
    const seq = ++state.quoteSeq;
    if (state.quoteController) state.quoteController.abort();
    const controller = new AbortController();
    state.quoteController = controller;
    const symbols = state.watchlist.join(",");
    try {
      const data = await apiJson(
        `/api/quotes?symbols=${encodeURIComponent(symbols)}&refresh=${force ? "1" : "0"}`,
        { signal: controller.signal },
      );
      if (seq !== state.quoteSeq) return;
      state.lastQuoteFetch = Date.now();
      const quotes = Array.isArray(data.quotes) ? data.quotes : [];
      for (const quote of quotes) {
        if (quote && quote.symbol) state.lastQuotes.set(quote.symbol, quote);
      }
      state.quoteController = null;
      updateWatchQuotes();
      updateFocusQuote();
      updateSourceIndicator(Array.isArray(data.errors) ? data.errors : []);
    } catch (error) {
      if (isAbortError(error)) return;
      if (seq !== state.quoteSeq) return;
      state.quoteController = null;
      updateSourceIndicator([{ message: error.message }]);
    }
  }

  async function refreshAllQuotes(force = false) {
    await Promise.allSettled([
      fetchMarketQuotes(force),
      fetchWatchQuotes(force),
    ]);
  }

  function renderMarket(data) {
    const host = $("tickerTrack");
    const quotes = Array.isArray(data && data.quotes) ? data.quotes : [];
    const bySymbol = new Map();
    for (const quote of quotes) {
      if (quote && quote.symbol) bySymbol.set(quote.symbol, quote);
    }
    const symbols = state.config.market_symbols || Object.keys(MARKET_META);
    host.innerHTML = "";
    let found = 0;

    for (const symbol of symbols) {
      const meta = MARKET_META[symbol] || { name: symbol, code: symbol };
      const quote = bySymbol.get(symbol);
      if (quote) found += 1;

      const item = document.createElement("div");
      item.className = "ticker-item";
      item.title = quote
        ? `${meta.name} ${formatPrice(quote.price)} ${formatPercent(quote.change_pct)}`
        : `${meta.name} 暂无行情`;

      const top = document.createElement("div");
      top.className = "ticker-top";
      const name = document.createElement("span");
      name.className = "ticker-name";
      name.textContent = meta.name;
      const code = document.createElement("span");
      code.className = "ticker-code";
      code.textContent = meta.code;
      top.append(name, code);

      const bottom = document.createElement("div");
      bottom.className = "ticker-bottom";
      const value = document.createElement("span");
      value.className = "ticker-value";
      value.textContent = quote ? formatPrice(quote.price) : "--";
      const change = document.createElement("span");
      change.className = "ticker-change";
      if (quote) {
        change.classList.add(toneClass(quote.change_pct));
        change.textContent = formatPercent(quote.change_pct);
      } else {
        change.classList.add("flat");
        change.textContent = "--";
      }
      bottom.append(value, change);
      item.append(top, bottom);
      host.appendChild(item);
    }

    if (!found) {
      renderMarketError();
      return;
    }
    $("marketAsOf").textContent = `更新 ${formatLocalTime(data.as_of)}`;
  }

  function renderMarketError() {
    $("tickerTrack").innerHTML = '<div class="ticker-error">指数行情暂不可用，将自动重试</div>';
    $("marketAsOf").textContent = "连接中断";
  }

  function marketClock() {
    return state.platform === "HK"
      ? { zone: "Asia/Hong_Kong", label: "香港时间", morningEnd: 720, dayEnd: 960, name: "港股时段" }
      : { zone: "Asia/Shanghai", label: "北京时间", morningEnd: 690, dayEnd: 900, name: "A 股时段" };
  }

  function updateMarketSession() {
    const element = $("marketSession");
    if (!element) return;
    const clock = marketClock();
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: clock.zone,
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date());
      const map = {};
      for (const part of parts) map[part.type] = part.value;
      const weekday = map.weekday || "";
      const hour = Number(map.hour) % 24;
      const minute = Number(map.minute);
      const total = hour * 60 + minute;
      const weekend = weekday === "Sat" || weekday === "Sun";
      let label = "休市";
      let suffix = "";
      if (weekend) {
        suffix = weekday === "Sat" ? "周六" : "周日";
      } else if (total < 570) {
        label = "盘前";
        suffix = `${map.hour}:${map.minute}`;
      } else if (total < clock.morningEnd) {
        label = "盘中";
        suffix = `${map.hour}:${map.minute}`;
      } else if (total < 780) {
        label = "午间休市";
        suffix = `${map.hour}:${map.minute}`;
      } else if (total < clock.dayEnd) {
        label = "盘中";
        suffix = `${map.hour}:${map.minute}`;
      } else {
        label = "盘后";
        suffix = `${map.hour}:${map.minute}`;
      }
      element.textContent = `${label} · ${clock.label} ${suffix}`;
    } catch (_error) {
      element.textContent = clock.name;
    }
  }

  function isTradingSession() {
    const clock = marketClock();
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: clock.zone,
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date());
      const map = {};
      for (const part of parts) map[part.type] = part.value;
      const weekday = map.weekday || "";
      if (weekday === "Sat" || weekday === "Sun") return false;
      const total = (Number(map.hour) % 24) * 3600 + Number(map.minute) * 60 + Number(map.second);
      return (total >= 34200 && total <= clock.morningEnd * 60) || (total >= 46800 && total <= clock.dayEnd * 60);
    } catch (_error) {
      return false;
    }
  }

  function chinaDateKey(value) {
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) return "";
    try {
      const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: marketClock().zone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).formatToParts(date);
      const map = {};
      for (const part of parts) map[part.type] = part.value;
      return `${map.year}-${map.month}-${map.day}`;
    } catch (_error) {
      return formatDateKey(date);
    }
  }

  async function fetchActiveQuote() {
    const symbol = state.activeSymbol;
    if (!symbol || state.liveController) return;
    const seq = ++state.liveSeq;
    const controller = new AbortController();
    state.liveController = controller;
    try {
      const data = await apiJson(
        `/api/quotes?symbols=${encodeURIComponent(symbol)}&refresh=1`,
        { signal: controller.signal },
      );
      if (seq !== state.liveSeq) return;
      state.liveController = null;
      const quote = (data.quotes || []).find((item) => item.symbol === symbol);
      if (!quote) return;
      const previous = state.liveQuotes.get(symbol);
      const changed = !previous
        || previous.price !== quote.price
        || previous.volume !== quote.volume
        || previous.day_high !== quote.day_high
        || previous.day_low !== quote.day_low;
      state.liveQuotes.set(symbol, quote);
      state.lastQuotes.set(symbol, quote);
      updateFocusQuote();
      if (changed && !isIntradayRange(state.range)) renderChart();
    } catch (error) {
      if (seq !== state.liveSeq) return;
      state.liveController = null;
      if (isAbortError(error)) return;
    }
  }

  function updateSourceIndicator(errors = []) {
    const sources = state.watchlist
      .map((symbol) => state.lastQuotes.get(symbol))
      .filter(Boolean)
      .map((quote) => quote.source || "");
    const dot = $("sourceDot");
    const label = $("sourceLabel");
    dot.classList.remove("is-live", "is-fallback", "is-error");

    if (!sources.length) {
      if (errors.length) {
        dot.classList.add("is-error");
        label.textContent = "DATA OFFLINE";
        label.title = "行情接口暂不可用";
      }
      return;
    }

    const primaryCount = sources.filter((source) => /东方财富|eastmoney/i.test(source)).length;
    const fallbackCount = sources.length - primaryCount;
    if (primaryCount && fallbackCount) {
      dot.classList.add("is-fallback");
      label.textContent = "东方财富 + 备用";
      label.title = "部分标的已切换到腾讯等备用行情源";
    } else if (primaryCount) {
      dot.classList.add("is-live");
      label.textContent = "东方财富";
      label.title = "全部股票行情来自东方财富";
    } else {
      dot.classList.add("is-fallback");
      label.textContent = "腾讯 / 备用";
      label.title = "东方财富当前不可用，已自动切换备用行情源";
    }
  }

  // -------------------------------------------------------------------------
  // Portfolio loading and orchestration
  // -------------------------------------------------------------------------

  function schedulePortfolioLoad({ refresh = false, delay = 300 } = {}) {
    window.clearTimeout(state.portfolioTimer);
    state.portfolioTimer = window.setTimeout(() => {
      void loadPortfolio({ refresh, autoAnalyze: true });
    }, delay);
  }

  async function loadPortfolio({ refresh = false, autoAnalyze = true } = {}) {
    state.detailSymbol = null;
    updateManualBuyButton();
    if (refresh) clearIntradayData();
    if (!state.selected.length) {
      resetWorkspace();
      return false;
    }
    window.clearTimeout(state.portfolioTimer);
    const requested = [...state.selected];
    const signature = selectedSignature(requested);
    const seq = ++state.portfolioSeq;
    abortPortfolioRequest();
    abortAnalysisRequest();
    state.analysisSeq += 1;
    stopAnalysisTimer();
    if (state.aiState === "loading") state.aiState = "idle";
    const controller = new AbortController();
    state.portfolioController = controller;
    state.loadingPortfolio = true;
    updateActionStates();

    try {
      const data = await apiJson(
        `/api/portfolio?symbols=${encodeURIComponent(requested.join(","))}&refresh=${refresh ? "1" : "0"}`,
        { signal: controller.signal },
      );
      if (seq !== state.portfolioSeq || selectedSignature() !== signature) return false;

      state.portfolioController = null;
      state.loadingPortfolio = false;
      state.portfolio = data;
      state.bundles = new Map();
      for (const item of data.symbols || []) {
        state.bundles.set(item.symbol, item);
        if (item.quote && item.quote.symbol) {
          state.lastQuotes.set(item.quote.symbol, item.quote);
        }
      }
      updateSourceIndicator();
      if (!state.activeSymbol || !state.bundles.has(state.activeSymbol)) {
        state.activeSymbol = state.bundles.size ? state.bundles.keys().next().value : null;
      }

      renderTabs();
      renderFocus();
      renderChart();
      renderMetrics();
      renderNews();
      updateWatchQuotes();
      showPortfolioNotice(data);
      updateSourceFromPortfolio(data);
      updateActionStates();

      const available = (data.symbols || []).length;
      const asOf = latestAsOf(data);
      const newsCount = (data.news_feed || []).length;
      updateWorkspaceMeta(
        `${available} 个标的 · 近两年日线${asOf ? ` · 截至 ${asOf}` : ""} · 新闻 ${newsCount} 条`,
      );

      if (autoAnalyze && state.config.ai_configured) {
        void runAnalysis({ force: refresh, manual: false });
      } else if (!state.config.ai_configured) {
        setAnalysisState("idle", "模型未配置");
        renderAiConfigured();
      } else {
        setAnalysisState("ready", "数据已就绪");
        renderAiWaitingForAnalysis();
      }
      return true;
    } catch (error) {
      if (isAbortError(error)) return false;
      if (seq !== state.portfolioSeq) return false;
      state.portfolioController = null;
      state.loadingPortfolio = false;
      state.aiState = "error";
      state.portfolio = null;
      state.bundles.clear();
      setAnalysisState("error", "行情获取失败");
      updateWorkspaceMeta("行情获取失败，请稍后重试");
      showChartOverlay("行情暂不可用");
      showNotice(`行情获取失败：${error.message || "请稍后重试"}`, true);
      renderMetricsEmpty("暂无数据");
      renderNewsEmpty("新闻不可用", "行情获取失败，新闻暂时无法匹配。");
      renderDataTable(null);
      renderAiError("行情数据未能加载，暂时无法进行研判。", "portfolio");
      updateActionStates();
      toast(error.message || "行情获取失败，请稍后重试", "error");
      return false;
    }
  }

  function abortPortfolioRequest() {
    if (state.portfolioController) {
      state.portfolioController.abort();
      state.portfolioController = null;
    }
  }

  async function openHoldingDetail(symbol, { refresh = false, name = "" } = {}) {
    const normalized = normalizeSymbol(symbol);
    if (!normalized) return false;
    if (
      !refresh &&
      state.detailSymbol === normalized &&
      state.portfolio &&
      !state.loadingPortfolio
    ) {
      return true;
    }
    if (refresh) clearIntradayData();
    window.clearTimeout(state.portfolioTimer);
    abortPortfolioRequest();
    abortAnalysisRequest();
    state.analysisSeq += 1;
    stopAnalysisTimer();
    const seq = ++state.portfolioSeq;
    const controller = new AbortController();
    state.portfolioController = controller;
    state.detailSymbol = normalized;
    state.loadingPortfolio = true;
    state.portfolio = null;
    state.bundles.clear();
    state.activeSymbol = normalized;
    state.analysisPayload = null;
    state.aiState = "idle";
    state.newsFilter = "all";
    state.newsLimit = 8;
    setAnalysisState("running", "持仓详情加载中");
    updateWorkspaceMeta(`正在读取 ${normalized} 的行情、指标与新闻`);
    clearNotice();
    renderTabs();
    renderFocus();
    renderMetricsLoading();
    renderNewsLoading();
    renderDataTable(null);
    showChartOverlay("正在装载持仓股票详情", true);
    renderAiHoldingDetail(normalized, name);
    if (state.accountSummary) renderPositions(state.accountSummary.positions);
    updateActionStates();

    try {
      const data = await apiJson(
        `/api/portfolio?symbols=${encodeURIComponent(normalized)}&refresh=${refresh ? "1" : "0"}`,
        { signal: controller.signal },
      );
      if (seq !== state.portfolioSeq) return false;
      state.portfolioController = null;
      state.loadingPortfolio = false;
      state.portfolio = data;
      state.bundles = new Map();
      for (const item of data.symbols || []) {
        state.bundles.set(item.symbol, item);
        if (item.quote && item.quote.symbol) {
          state.lastQuotes.set(item.quote.symbol, item.quote);
        }
      }
      if (!state.bundles.has(state.activeSymbol)) {
        state.activeSymbol = state.bundles.size ? state.bundles.keys().next().value : null;
      }
      updateSourceIndicator();
      renderTabs();
      renderFocus();
      renderChart();
      renderMetrics();
      renderNews();
      updateWatchQuotes();
      showPortfolioNotice(data);
      updateSourceFromPortfolio(data);
      const bundle = state.activeSymbol ? state.bundles.get(state.activeSymbol) : null;
      const displayName = (bundle && bundle.name) || state.activeSymbol || normalized;
      const asOf = latestAsOf(data);
      const newsCount = (data.news_feed || []).length;
      updateWorkspaceMeta(
        `持仓详情 · ${displayName}${asOf ? ` · 截至 ${asOf}` : ""} · 新闻 ${newsCount} 条`,
      );
      setAnalysisState("ready", "持仓详情");
      renderAiHoldingDetail(state.activeSymbol || normalized, displayName);
      updateActionStates();
      if (state.accountSummary) renderPositions(state.accountSummary.positions);
      return true;
    } catch (error) {
      if (isAbortError(error)) return false;
      if (seq !== state.portfolioSeq) return false;
      state.portfolioController = null;
      state.loadingPortfolio = false;
      state.portfolio = null;
      state.bundles.clear();
      setAnalysisState("error", "行情获取失败");
      updateWorkspaceMeta("持仓股票行情获取失败，请稍后重试");
      showChartOverlay("行情暂不可用");
      showNotice(`行情获取失败：${error.message || "请稍后重试"}`, true);
      renderMetricsEmpty("暂无数据");
      renderNewsEmpty("新闻不可用", "行情获取失败，新闻暂时无法匹配。");
      renderDataTable(null);
      updateActionStates();
      toast(error.message || "行情获取失败", "error");
      return false;
    }
  }

  function latestAsOf(portfolio) {
    const dates = (portfolio.symbols || [])
      .map((item) => item.metrics && item.metrics.as_of)
      .filter(Boolean)
      .sort();
    return dates.length ? dates[dates.length - 1] : "";
  }

  function updateSourceFromPortfolio(portfolio) {
    if (state.lastQuotes.size) return;
    const providers = (portfolio && portfolio.providers) || [];
    if (!providers.length) return;
    const dot = $("sourceDot");
    const label = $("sourceLabel");
    dot.classList.remove("is-live", "is-fallback", "is-error");
    const primary = providers.some((provider) => /东方财富|eastmoney/i.test(provider));
    const fallback = providers.some((provider) => /腾讯|tencent|sina|yahoo/i.test(provider));
    if (primary && !fallback) {
      dot.classList.add("is-live");
      label.textContent = "东方财富";
    } else {
      dot.classList.add("is-fallback");
      label.textContent = primary ? "东方财富 + 备用" : "备用数据源";
    }
  }

  function updateWorkspaceMeta(text) {
    $("workspaceMeta").textContent = text;
  }

  function showNotice(message, isError = false) {
    const notice = $("portfolioNotice");
    notice.textContent = message;
    notice.classList.remove("hidden");
    notice.classList.toggle("is-error", isError);
  }

  function clearNotice() {
    const notice = $("portfolioNotice");
    notice.textContent = "";
    notice.classList.add("hidden");
    notice.classList.remove("is-error");
  }

  function showPortfolioNotice(portfolio) {
    const errors = portfolio.errors || [];
    const warnings = portfolio.warnings || [];
    const messages = [];
    if (errors.length) {
      messages.push(`未能获取 ${errors.map((item) => item.symbol).join("、")} 的完整行情。`);
    }
    for (const warning of warnings) {
      if (!messages.includes(warning)) messages.push(warning);
    }
    if (!messages.length) {
      clearNotice();
      return;
    }
    const extra = messages.length > 2 ? ` 另有 ${messages.length - 2} 条提示。` : "";
    showNotice(messages.slice(0, 2).join(" ") + extra, errors.length > 0);
  }

  // -------------------------------------------------------------------------
  // Active symbol, focus quote and tabs
  // -------------------------------------------------------------------------

  function renderTabs() {
    const host = $("symbolTabs");
    host.innerHTML = "";
    const symbols = state.portfolio
      ? (state.portfolio.symbols || []).map((item) => item.symbol)
      : state.detailSymbol
        ? [state.detailSymbol]
        : state.selected;
    if (!symbols.length) return;

    if (!state.activeSymbol || !symbols.includes(state.activeSymbol)) {
      state.activeSymbol = symbols[0];
    }

    const fragment = document.createDocumentFragment();
    for (const symbol of symbols) {
      const bundle = state.bundles.get(symbol);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `symbol-tab${symbol === state.activeSymbol ? " is-active" : ""}`;
      button.dataset.symbol = symbol;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(symbol === state.activeSymbol));
      button.setAttribute("tabindex", symbol === state.activeSymbol ? "0" : "-1");
      button.setAttribute("aria-controls", "chart");
      if (bundle) button.title = bundle.name || symbol;
      const dot = document.createElement("span");
      dot.className = "tab-dot";
      const label = document.createElement("span");
      label.textContent = symbol;
      button.append(dot, label);
      fragment.appendChild(button);
    }
    host.appendChild(fragment);
  }

  function activateSymbol(symbol, focusTab = false) {
    const available = state.portfolio
      ? (state.portfolio.symbols || []).map((item) => item.symbol)
      : state.detailSymbol
        ? [state.detailSymbol]
        : state.selected;
    if (!available.includes(symbol)) return;
    state.activeSymbol = symbol;
    renderTabs();
    renderFocus();
    renderChart();
    renderMetrics();
    renderDataTable(null);
    const activeTab = $("symbolTabs").querySelector(`[data-symbol="${CSS.escape(symbol)}"]`);
    if (activeTab) {
      activeTab.scrollIntoView({ block: "nearest", inline: "nearest" });
      if (focusTab) activeTab.focus({ preventScroll: true });
    }
  }

  function focusQuote() {
    const symbol = state.activeSymbol;
    if (!symbol) return null;
    return state.lastQuotes.get(symbol) || (state.bundles.get(symbol) || {}).quote || null;
  }

  function renderFocus() {
    const symbol = state.activeSymbol;
    const bundle = symbol ? state.bundles.get(symbol) : null;
    const quote = symbol ? focusQuote() : null;

    $("activeSymbol").textContent = symbol || "--";
    let exchange = "";
    if (quote && quote.exchange) exchange = quote.exchange;
    else if (symbol && symbol.endsWith(".HK")) exchange = "HKEX";
    else if (symbol && symbol.endsWith(".SS")) exchange = "SSE";
    else if (symbol && symbol.endsWith(".SZ")) exchange = "SZSE";
    else if (symbol && symbol.endsWith(".BJ")) exchange = "BSE";
    if (quote && quote.currency) exchange = exchange ? `${exchange} · ${quote.currency}` : quote.currency;
    $("activeExchange").textContent = exchange;
    $("activeName").textContent = bundle
      ? bundle.name || symbol
      : quote
        ? quote.name || "行情加载中"
        : state.loadingPortfolio
          ? "行情加载中"
          : symbol
            ? "等待行情"
            : "选择标的后加载";

    renderFocusQuote();
  }

  function renderFocusQuote() {
    const symbol = state.activeSymbol;
    const quote = symbol ? focusQuote() : null;
    const price = $("activePrice");
    const change = $("activeChange");
    if (!quote) {
      price.textContent = "--";
      change.innerHTML = '<span class="change-abs">--</span>';
      renderQuoteMeta(null);
      return;
    }
    price.textContent = formatPrice(quote.price);
    const tone = toneClass(quote.change_pct);
    change.innerHTML = "";
    const main = document.createElement("span");
    main.className = tone;
    main.textContent = formatPercent(quote.change_pct);
    const absolute = document.createElement("span");
    absolute.className = `change-abs ${tone}`;
    absolute.textContent = formatSignedPrice(quote.change);
    change.append(main, absolute);
    renderQuoteMeta(quote);
  }

  function updateFocusQuote() {
    if (!state.activeSymbol || !state.portfolio) return;
    renderFocusQuote();
  }

  function renderQuoteMeta(quote) {
    const host = $("quoteMeta");
    host.innerHTML = "";
    if (!quote) {
      const item = document.createElement("span");
      item.textContent = state.activeSymbol
        ? state.loadingPortfolio
          ? "行情加载中"
          : "等待行情"
        : "选择标的后加载";
      host.appendChild(item);
      return;
    }
    const fields = [
      ["开盘", formatPrice(quote.open)],
      ["最高", formatPrice(quote.day_high)],
      ["最低", formatPrice(quote.day_low)],
      ["昨收", formatPrice(quote.previous_close)],
      ["成交量", formatVolume(quote.volume)],
    ];
    for (const [label, value] of fields) {
      if (value === "--") continue;
      const item = document.createElement("span");
      item.className = "meta-item";
      item.textContent = `${label} ${value}`;
      host.appendChild(item);
    }
    if (quote.source) {
      const source = document.createElement("span");
      source.className = "meta-item quote-source";
      source.textContent = quote.source;
      source.title = "当前行情数据源";
      host.appendChild(source);
    }
  }

  // -------------------------------------------------------------------------
  // Chart
  // -------------------------------------------------------------------------

  function initChart() {
    if (!window.echarts) {
      showChartOverlay("图表组件未加载");
      return;
    }
    const element = $("chart");
    if (!state.chart) {
      state.chart = window.echarts.init(element, null, { renderer: "canvas" });
    }
    if (!state.chartObserver && "ResizeObserver" in window) {
      state.chartObserver = new ResizeObserver(() => {
        if (!state.chart) return;
        window.requestAnimationFrame(() => {
          if (state.chart) state.chart.resize();
        });
      });
      state.chartObserver.observe(element.parentElement);
    }
    if (!state.chartResizeBound) {
      state.chartResizeBound = true;
      window.addEventListener("resize", () => {
        if (state.chart) state.chart.resize();
      });
    }
  }

  function showChartOverlay(text, scanning = false) {
    const overlay = $("chartLoading");
    if (!overlay) return;
    overlay.classList.remove("hidden");
    const scan = overlay.querySelector(".scan-line");
    if (scan) scan.style.display = scanning ? "" : "none";
    const label = overlay.querySelector("span:last-child");
    if (label) label.textContent = text;
    $("chart").setAttribute("aria-busy", scanning ? "true" : "false");
  }

  function hideChartOverlay() {
    const overlay = $("chartLoading");
    if (overlay) overlay.classList.add("hidden");
    $("chart").setAttribute("aria-busy", "false");
  }

  function parseDateKey(value) {
    const parts = String(value || "").split("-");
    if (parts.length !== 3) return null;
    const year = Number(parts[0]);
    const month = Number(parts[1]);
    const day = Number(parts[2]);
    if (!year || !month || !day) return null;
    return new Date(year, month - 1, day);
  }

  function formatDateKey(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function rangeStartIndex(dates, range) {
    const total = dates.length;
    if (!total) return 0;
    const last = parseDateKey(dates[total - 1]);
    if (!last) return Math.max(0, total - 132);
    let cutoff;
    switch (range) {
      case "DAY":
        cutoff = new Date(last.getFullYear(), last.getMonth(), last.getDate());
        break;
      case "WEEK": {
        const offset = (last.getDay() + 6) % 7;
        cutoff = new Date(last.getFullYear(), last.getMonth(), last.getDate() - offset);
        break;
      }
      case "MONTH": {
        // 近 1 月：从最后一个交易日往前推一个月，而不是自然月月初。
        const targetMonth = (last.getMonth() - 1 + 12) % 12;
        cutoff = new Date(last.getFullYear(), last.getMonth() - 1, last.getDate());
        if (cutoff.getMonth() !== targetMonth) {
          // 上个月没有这一天（如 3/31 → 2 月），退回该月最后一天。
          cutoff = new Date(last.getFullYear(), last.getMonth(), 0);
        }
        break;
      }
      case "3M":
        cutoff = new Date(last.getFullYear(), last.getMonth() - 2, 1);
        break;
      case "6M":
        cutoff = new Date(last.getFullYear(), last.getMonth() - 5, 1);
        break;
      case "YEAR":
        cutoff = new Date(last.getFullYear(), 0, 1);
        break;
      default:
        cutoff = new Date(last.getFullYear(), last.getMonth() - 5, 1);
    }
    const key = formatDateKey(cutoff);
    const index = dates.findIndex((value) => value >= key);
    return index < 0 ? total - 1 : index;
  }

  function rollingMean(values, window) {
    const result = new Array(values.length).fill(null);
    let sum = 0;
    for (let index = 0; index < values.length; index += 1) {
      sum += values[index];
      if (index >= window) sum -= values[index - window];
      if (index >= window - 1) result[index] = sum / window;
    }
    return result;
  }

  function applyLiveQuote(bundle) {
    const quote = bundle && state.liveQuotes.get(bundle.symbol);
    const history = bundle && bundle.history;
    if (!quote || !history || !Array.isArray(history.dates) || !history.dates.length) return null;
    const price = toFiniteNumber(quote.price);
    if (!price || price <= 0) return null;
    const today = chinaDateKey();
    if (quote.quote_time && chinaDateKey(quote.quote_time) !== today) return null;
    const lastDate = history.dates[history.dates.length - 1];
    if (lastDate !== today && !isTradingSession()) return null;

    const dates = history.dates.slice();
    const candles = (history.candles || []).map((candle) => candle.slice());
    const volume = (history.volume || []).slice();
    const open = toFiniteNumber(quote.open) || price;
    const dayHigh = Math.max(toFiniteNumber(quote.day_high) || price, price);
    const dayLow = Math.min(toFiniteNumber(quote.day_low) || price, price);
    const dayVolume = toFiniteNumber(quote.volume);

    if (lastDate === today) {
      const index = dates.length - 1;
      const existing = candles[index] || [open, price, dayLow, dayHigh];
      const candleOpen = existing[0] || open;
      candles[index] = [
        candleOpen,
        price,
        Math.min(existing[2] || dayLow, dayLow),
        Math.max(existing[3] || dayHigh, dayHigh),
      ];
      if (dayVolume !== null) volume[index] = dayVolume;
    } else {
      dates.push(today);
      candles.push([open, price, dayLow, dayHigh]);
      volume.push(dayVolume === null ? 0 : dayVolume);
    }

    const close = candles.map((candle) => candle[1]);
    return {
      dates,
      candles,
      volume,
      close,
      ma20: rollingMean(close, 20),
      ma50: rollingMean(close, 50),
    };
  }

  function chartSeriesData() {
    const bundle = state.activeSymbol ? state.bundles.get(state.activeSymbol) : null;
    if (!bundle || !bundle.history || !Array.isArray(bundle.history.dates)) return null;
    const history = applyLiveQuote(bundle) || bundle.history;
    const total = history.dates.length;
    if (!total) return null;
    const start = rangeStartIndex(history.dates, state.range);
    return {
      dates: history.dates.slice(start),
      candles: (history.candles || []).slice(start),
      volume: (history.volume || []).slice(start),
      close: (history.close || []).slice(start),
      ma20: (history.ma20 || []).slice(start),
      ma50: (history.ma50 || []).slice(start),
      start,
      total,
    };
  }

  function currentChartData() {
    return isIntradayRange(state.range) ? intradaySeriesData() : chartSeriesData();
  }

  function isIntradayRange(range) {
    return range === "DAY" || range === "WEEK";
  }

  function intradayKey(symbol, range) {
    return `${symbol}|${range}`;
  }

  function intradaySeriesData() {
    if (!state.activeSymbol) return null;
    const raw = state.intraday.get(intradayKey(state.activeSymbol, state.range));
    if (!raw) return null;
    const useCandles = state.mode === "candle";
    const source = useCandles ? raw.candles : raw.points;
    if (!Array.isArray(source) || !source.length) return null;
    const dates = source.map((item) => item.time);
    const candles = useCandles
      ? source.map((item) => [item.open, item.close, item.low, item.high])
      : source.map((item) => [item.price, item.price, item.price, item.price]);
    const close = useCandles
      ? source.map((item) => item.close)
      : source.map((item) => item.price);
    const volume = source.map((item) => item.volume || 0);
    return {
      dates,
      candles,
      volume,
      close,
      ma20: dates.map(() => null),
      ma50: dates.map(() => null),
      kind: "intraday",
      granularity: useCandles ? "minute" : raw.granularity,
      preClose: raw.pre_close,
      points: useCandles ? null : source,
      intraday: raw,
      start: 0,
      total: source.length,
    };
  }

  function clearIntradayData() {
    for (const controller of state.intradayControllers.values()) controller.abort();
    state.intradayControllers.clear();
    state.intradayPending.clear();
    state.intraday.clear();
    state.intradayErrors.clear();
  }

  function ensureIntraday(symbol, range, { refresh = false } = {}) {
    if (!symbol || !isIntradayRange(range)) return;
    const key = intradayKey(symbol, range);
    if (refresh) {
      state.intradayErrors.delete(key);
    }
    if (state.intraday.has(key) && !refresh) return;
    if (state.intradayPending.has(key)) return;

    const previous = state.intradayControllers.get(key);
    if (previous) previous.abort();
    const controller = new AbortController();
    state.intradayControllers.set(key, controller);
    state.intradayPending.add(key);
    state.intradayErrors.delete(key);
    if (
      !state.intraday.has(key) &&
      state.activeSymbol === symbol &&
      state.range === range
    ) {
      showChartOverlay("正在装载分时数据", true);
      $("chart").setAttribute("aria-busy", "true");
    }

    apiJson(
      `/api/intraday?symbol=${encodeURIComponent(symbol)}&range=${range}&refresh=${refresh ? "1" : "0"}`,
      { signal: controller.signal },
    )
      .then((data) => {
        if (state.intradayControllers.get(key) !== controller) return;
        state.intradayControllers.delete(key);
        state.intradayPending.delete(key);
        const previous = state.intraday.get(key);
        const previousPoint = previous && previous.points && previous.points.length
          ? previous.points[previous.points.length - 1]
          : null;
        const nextPoint = data.points && data.points.length
          ? data.points[data.points.length - 1]
          : null;
        const previousCandle = previous && previous.candles && previous.candles.length
          ? previous.candles[previous.candles.length - 1]
          : null;
        const nextCandle = data.candles && data.candles.length
          ? data.candles[data.candles.length - 1]
          : null;
        const changed = !previous
          || previous.as_of !== data.as_of
          || (previousPoint && nextPoint && previousPoint.price !== nextPoint.price)
          || (previousCandle && nextCandle && previousCandle.close !== nextCandle.close);
        state.intraday.set(key, data);
        state.intradayErrors.delete(key);
        if (state.activeSymbol === symbol && state.range === range && changed) {
          renderChart();
        }
      })
      .catch((error) => {
        if (state.intradayControllers.get(key) !== controller) return;
        state.intradayControllers.delete(key);
        state.intradayPending.delete(key);
        if (isAbortError(error)) return;
        state.intradayErrors.set(key, error.message || "分时数据暂不可用");
        if (
          !state.intraday.has(key) &&
          state.activeSymbol === symbol &&
          state.range === range
        ) {
          renderChart();
        }
      });
  }

  function intradayDirectionLabel(direction) {
    if (direction === "buy") return "买盘";
    if (direction === "sell") return "卖盘";
    return "中性";
  }

  function intradayChangePct(data, index) {
    const price = toFiniteNumber(data.close[index]);
    if (price === null) return null;
    const preClose = toFiniteNumber(data.preClose);
    if (preClose) return (price / preClose - 1) * 100;
    if (index > 0) {
      const previous = toFiniteNumber(data.close[index - 1]);
      if (previous) return (price / previous - 1) * 100;
    }
    return null;
  }

  function renderChart() {
    const symbol = state.activeSymbol;
    const bundle = symbol ? state.bundles.get(symbol) : null;
    const intradayMode = isIntradayRange(state.range);
    const data = currentChartData();
    const chartElement = $("chart");

    if (!symbol) {
      if (state.chart) state.chart.clear();
      showChartOverlay("选择标的后显示走势");
      updateChartFooter(null);
      renderDataTable(null);
      chartElement.setAttribute("aria-label", "尚未选择股票");
      return;
    }
    if (!bundle) {
      if (state.chart) state.chart.clear();
      showChartOverlay(state.loadingPortfolio ? "正在装载两年日线" : "该标的行情暂不可用", state.loadingPortfolio);
      updateChartFooter(null);
      renderDataTable(null);
      chartElement.setAttribute("aria-label", `${symbol} 行情暂不可用`);
      return;
    }
    if (intradayMode && !data) {
      if (state.chart) state.chart.clear();
      const key = intradayKey(symbol, state.range);
      const error = state.intradayErrors.get(key);
      if (error) {
        showChartOverlay(`分时数据暂不可用：${error}`);
        chartElement.setAttribute("aria-label", `${symbol} 分时数据暂不可用`);
      } else {
        ensureIntraday(symbol, state.range);
        showChartOverlay(state.mode === "candle" ? "正在装载分时 K 线" : "正在装载分时走势", true);
        chartElement.setAttribute("aria-label", `${symbol} 分时数据加载中`);
      }
      updateChartFooter(null);
      renderDataTable(null);
      return;
    }
    if (!data) {
      if (state.chart) state.chart.clear();
      showChartOverlay(state.loadingPortfolio ? "正在装载两年日线" : "该标的行情暂不可用", state.loadingPortfolio);
      updateChartFooter(null);
      renderDataTable(null);
      chartElement.setAttribute("aria-label", `${symbol} 行情暂不可用`);
      return;
    }

    initChart();
    if (!state.chart) {
      showChartOverlay("图表组件未加载");
      updateChartFooter(data);
      renderDataTable(data);
      return;
    }

    const axisColor = "#343b31";
    const gridLine = "#1b1f1a";
    const muted = "#747c70";
    const mono = '"Cascadia Mono", "JetBrains Mono", Consolas, monospace';
    const dates = data.dates;
    const candles = data.candles;
    const upColor = "#69d6a0";
    const downColor = "#ef6f6a";
    const labelInterval = Math.max(0, Math.floor(dates.length / 6) - 1);
    const volumeData = data.volume.map((value, index) => {
      const candle = candles[index] || [0, 0];
      const rising = candle[1] >= candle[0];
      return {
        value,
        itemStyle: {
          color: rising ? "rgba(105, 214, 160, 0.34)" : "rgba(239, 111, 106, 0.34)",
        },
      };
    });

    const metrics = bundle.metrics || {};
    const markData = [];
    if (data.kind === "intraday") {
      const preClose = toFiniteNumber(data.preClose);
      if (preClose !== null) {
        markData.push({
          yAxis: preClose,
          name: "昨收",
          label: { formatter: `昨收 ${formatPrice(preClose)}`, color: "#929a8d" },
          lineStyle: { color: "rgba(146, 154, 141, 0.42)" },
        });
      }
    } else {
      // 日 K 的 20 日支撑 / 阻力始终绘制，不再因为不在可视区间内而隐藏。
      const support = toFiniteNumber(metrics.support_20d);
      const resistance = toFiniteNumber(metrics.resistance_20d);
      if (support !== null) {
        markData.push({
          yAxis: support,
          name: "支撑",
          label: { formatter: `支撑 ${formatPrice(support)}`, color: "#7fae96" },
          lineStyle: { color: "rgba(105, 214, 160, 0.42)" },
        });
      }
      if (resistance !== null) {
        markData.push({
          yAxis: resistance,
          name: "阻力",
          label: { formatter: `阻力 ${formatPrice(resistance)}`, color: "#c48f8c" },
          lineStyle: { color: "rgba(239, 111, 106, 0.38)" },
        });
      }
    }
    const markLine = markData.length
      ? {
          symbol: "none",
          silent: true,
          animation: false,
          label: {
            position: "insideEndTop",
            fontSize: 9,
            fontFamily: mono,
            padding: [2, 3, 0, 3],
          },
          lineStyle: { type: "dashed", width: 1, opacity: 1 },
          data: markData,
        }
      : undefined;

    const priceSeries = state.mode === "candle"
      ? {
          name: "价格",
          type: "candlestick",
          data: candles,
          itemStyle: {
            color: "rgba(105, 214, 160, 0.13)",
            color0: "rgba(239, 111, 106, 0.13)",
            borderColor: upColor,
            borderColor0: downColor,
            borderWidth: 1,
          },
          markLine,
          emphasis: {
            itemStyle: {
              color: "rgba(105, 214, 160, 0.28)",
              color0: "rgba(239, 111, 106, 0.28)",
              borderColor: upColor,
              borderColor0: downColor,
            },
          },
        }
      : {
          name: "收盘",
          type: "line",
          data: data.close,
          showSymbol: false,
          smooth: false,
          lineStyle: { width: 2, color: "#d8ddd4" },
          areaStyle: {
            color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(216, 221, 212, 0.13)" },
              { offset: 1, color: "rgba(216, 221, 212, 0.005)" },
            ]),
          },
          emphasis: { disabled: true },
          markLine,
        };

    const option = {
      backgroundColor: "transparent",
      animation: !REDUCED_MOTION,
      animationDuration: 420,
      animationEasing: "cubicOut",
      textStyle: { fontFamily: mono, color: muted, fontSize: 9 },
      grid: [
        { left: 12, right: 62, top: 18, height: "61%" },
        { left: 12, right: 62, top: "76%", height: "15%" },
      ],
      axisPointer: {
        link: [{ xAxisIndex: "all" }],
        lineStyle: { color: "#4a5146", width: 1 },
        label: {
          backgroundColor: "#1d221c",
          borderColor: "#3a4036",
          borderWidth: 1,
          color: "#dfe3da",
          fontSize: 9,
          fontFamily: mono,
          padding: [4, 6],
        },
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: "rgba(17, 20, 16, 0.97)",
        borderColor: "#343b31",
        borderWidth: 1,
        padding: 0,
        textStyle: { color: "#e9ece5", fontSize: 10, fontFamily: mono },
        extraCssText: "box-shadow: 0 16px 44px rgba(0,0,0,0.55); border-radius: 3px;",
        formatter(params) {
          if (!params || !params.length) return "";
          const index = params[0].dataIndex;
          const candle = candles[index];
          const date = dates[index];
          if (!candle) return "";
          const isIntraday = data.kind === "intraday";
          let change;
          if (isIntraday) {
            change = intradayChangePct(data, index);
          } else {
            const previous = index > 0 ? candles[index - 1] : null;
            change = previous && previous[1] ? (candle[1] / previous[1] - 1) * 100 : null;
          }
          const tone = candle[1] >= candle[0] ? upColor : downColor;
          const changeColor = change === null ? muted : change >= 0 ? upColor : downColor;
          const changeText = change === null ? "--" : `${change > 0 ? "+" : ""}${change.toFixed(2)}%`;
          let rows;
          if (isIntraday && state.mode === "line") {
            rows = [
              ["价格", formatPrice(candle[1])],
              ["涨跌", changeText],
              ["成交量", formatVolume(data.volume[index])],
            ];
            const point = data.points ? data.points[index] : null;
            if (point && point.direction) {
              rows.push(["方向", intradayDirectionLabel(point.direction)]);
            }
          } else {
            rows = [
              ["开盘", formatPrice(candle[0])],
              ["最高", formatPrice(candle[3])],
              ["最低", formatPrice(candle[2])],
              ["收盘", formatPrice(candle[1])],
              ["涨跌", changeText],
              ["成交量", formatVolume(data.volume[index])],
            ];
          }
          const body = rows
            .map(
              ([label, value]) =>
                `<div style="display:flex;justify-content:space-between;gap:24px;line-height:1.7"><span style="color:#747c70">${label}</span><span style="color:${label === "涨跌" ? changeColor : label === "收盘" || label === "价格" ? tone : "#e9ece5"}">${value}</span></div>`,
            )
            .join("");
          return `<div style="min-width:166px;padding:9px 11px"><div style="color:#929a8d;font-size:9px;letter-spacing:.05em;margin-bottom:5px">${escapeHtml(date)}</div>${body}</div>`;
        },
      },
      xAxis: [
        {
          type: "category",
          data: dates,
          boundaryGap: true,
          axisLine: { lineStyle: { color: axisColor } },
          axisTick: { show: false },
          axisLabel: { show: false },
          splitLine: { show: false },
          axisPointer: { label: { show: false } },
        },
        {
          type: "category",
          gridIndex: 1,
          data: dates,
          boundaryGap: true,
          axisLine: { lineStyle: { color: axisColor } },
          axisTick: { show: false },
          axisLabel: {
            color: muted,
            fontSize: 8.5,
            fontFamily: mono,
            interval: labelInterval,
            margin: 9,
            showMinLabel: data.kind === "intraday" ? false : true,
            formatter: (value) => {
              const text = String(value);
              if (data.kind === "intraday") {
                return state.range === "DAY" ? text.slice(11) : text.slice(5);
              }
              return text.slice(5);
            },
          },
          splitLine: { show: false },
        },
      ],
      yAxis: [
        {
          type: "value",
          scale: true,
          position: "right",
          splitNumber: 4,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: muted,
            fontSize: 8.5,
            fontFamily: mono,
            margin: 10,
            formatter: (value) => {
              if (data.kind === "intraday") {
                return formatPrice(value, Math.abs(value) < 1 ? 3 : 2);
              }
              return formatPrice(value, 0);
            },
          },
          splitLine: { lineStyle: { color: gridLine, type: "dashed" } },
        },
        {
          type: "value",
          gridIndex: 1,
          scale: true,
          position: "right",
          splitNumber: 2,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: "#596055",
            fontSize: 8,
            fontFamily: mono,
            margin: 10,
            formatter: (value) => formatVolumeAxis(value),
          },
          splitLine: { show: false },
        },
      ],
      series: [
        priceSeries,
        ...(data.kind === "intraday"
          ? []
          : [
              {
                name: "MA20",
                type: "line",
                data: data.ma20,
                showSymbol: false,
                smooth: false,
                connectNulls: false,
                lineStyle: { width: 1.4, color: "#e7a25e", opacity: 0.9 },
                emphasis: { disabled: true },
                silent: true,
                z: 3,
              },
              {
                name: "MA50",
                type: "line",
                data: data.ma50,
                showSymbol: false,
                smooth: false,
                connectNulls: false,
                lineStyle: { width: 1.2, color: "#9ca9b9", opacity: 0.72 },
                emphasis: { disabled: true },
                silent: true,
                z: 2,
              },
            ]),
        {
          name: "成交量",
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumeData,
          barWidth: "58%",
          emphasis: { disabled: true },
          silent: true,
        },
      ],
    };

    state.chart.setOption(option, true);
    state.chart.resize();
    hideChartOverlay();
    updateChartFooter(data);
    renderDataTable(data);
    const unit = data.kind === "intraday"
      ? (data.granularity === "tick" ? "个逐笔数据点" : "个分钟数据点")
      : "个交易日";
    const label = `${symbol} ${RANGE_LABELS[state.range] || state.range} ${state.mode === "candle" ? "K线" : "走势"}，${dates.length} ${unit}`;
    chartElement.setAttribute("aria-label", label);
  }

  function updateChartFooter(data) {
    if (!data) {
      $("ma20Value").textContent = "--";
      $("ma50Value").textContent = "--";
      $("upDays").textContent = "--";
      $("downDays").textContent = "--";
      return;
    }
    if (data.kind === "intraday") {
      $("ma20Value").textContent = "--";
      $("ma50Value").textContent = "--";
      let up = 0;
      let down = 0;
      for (let index = 1; index < data.close.length; index += 1) {
        if (data.close[index] > data.close[index - 1]) up += 1;
        else if (data.close[index] < data.close[index - 1]) down += 1;
      }
      $("upDays").textContent = String(up);
      $("downDays").textContent = String(down);
      return;
    }
    const lastMa = (series) => {
      for (let index = series.length - 1; index >= 0; index -= 1) {
        if (toFiniteNumber(series[index]) !== null) return series[index];
      }
      return null;
    };
    $("ma20Value").textContent = formatPrice(lastMa(data.ma20));
    $("ma50Value").textContent = formatPrice(lastMa(data.ma50));
    let up = 0;
    let down = 0;
    for (const candle of data.candles) {
      if (candle[1] >= candle[0]) up += 1;
      else down += 1;
    }
    $("upDays").textContent = String(up);
    $("downDays").textContent = String(down);
  }

  function renderDataTable(data, force = false) {
    const wrap = $("dataTableWrap");
    if (!force && wrap && wrap.classList.contains("hidden")) return;
    const head = document.querySelector("#dataTable thead");
    const body = $("dataTableBody");
    const dailyHead = "<tr><th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th><th>成交量</th></tr>";
    if (!data || !data.candles || !data.candles.length) {
      if (head) head.innerHTML = dailyHead;
      body.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#596055;padding:18px">暂无数据</td></tr>';
      return;
    }

    if (data.kind === "intraday" && state.mode !== "candle") {
      const hasDirection = Boolean(data.points && data.points.some((point) => point.direction));
      if (head) {
        head.innerHTML = `<tr><th>时间</th><th>价格</th><th>涨跌</th><th>成交量</th>${hasDirection ? "<th>方向</th>" : ""}</tr>`;
      }
      const rows = [];
      for (let index = data.candles.length - 1; index >= 0; index -= 1) {
        const price = data.close[index];
        const change = intradayChangePct(data, index);
        const tone = change === null ? "flat" : change > 0 ? "up" : change < 0 ? "down" : "flat";
        const point = data.points ? data.points[index] : null;
        const directionCell = hasDirection
          ? `<td>${escapeHtml(intradayDirectionLabel(point && point.direction))}</td>`
          : "";
        rows.push(
          `<tr><td>${escapeHtml(data.dates[index])}</td><td class="${tone}">${formatPrice(price)}</td><td class="${tone}">${formatPercent(change)}</td><td>${formatVolume(data.volume[index])}</td>${directionCell}</tr>`,
        );
      }
      body.innerHTML = rows.join("");
      return;
    }

    if (head) {
      head.innerHTML = data.kind === "intraday"
        ? "<tr><th>时间</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th><th>成交量</th></tr>"
        : dailyHead;
    }
    const rows = [];
    for (let index = data.candles.length - 1; index >= 0; index -= 1) {
      const candle = data.candles[index];
      const tone = candle[1] >= candle[0] ? "up" : "down";
      rows.push(
        `<tr><td>${escapeHtml(data.dates[index])}</td><td>${formatPrice(candle[0])}</td><td>${formatPrice(candle[3])}</td><td>${formatPrice(candle[2])}</td><td class="${tone}">${formatPrice(candle[1])}</td><td>${formatVolume(data.volume[index])}</td></tr>`,
      );
    }
    body.innerHTML = rows.join("");
  }

  // -------------------------------------------------------------------------
  // Metrics
  // -------------------------------------------------------------------------

  function metricCell(label, value, sub, options = {}) {
    const valueClass = options.tone ? ` ${options.tone}` : "";
    const sizeClass = options.small ? " is-small" : "";
    const meter = options.meter === null || options.meter === undefined
      ? ""
      : `<div class="range-meter" aria-hidden="true"><span class="range-meter-fill" style="width:${Math.max(0, Math.min(100, options.meter))}%"></span><span class="range-meter-dot" style="left:${Math.max(0, Math.min(100, options.meter))}%"></span></div>`;
    const subClass = options.subTone ? ` ${options.subTone}` : "";
    return `<div class="metric-cell"><div class="metric-label">${escapeHtml(label)}</div><div class="metric-value${sizeClass}${valueClass}">${escapeHtml(value)}</div>${meter}<div class="metric-sub${subClass}">${escapeHtml(sub)}</div></div>`;
  }

  function renderMetricsLoading() {
    $("metricsRow").setAttribute("aria-busy", "true");
    $("metricsRow").innerHTML = Array.from(
      { length: 6 },
      () => '<div class="metric-cell skeleton-cell"></div>',
    ).join("");
  }

  function renderMetricsEmpty(reason) {
    $("metricsRow").setAttribute("aria-busy", "false");
    $("metricsRow").innerHTML = [
      metricCell("1M 回报", "--", reason),
      metricCell("RSI14", "--", reason),
      metricCell("30D 波动率", "--", reason),
      metricCell("52W 位置", "--", reason, { meter: 0 }),
      metricCell("20D 支撑 / 阻力", "--", reason, { small: true }),
      metricCell("趋势", "--", reason),
    ].join("");
  }

  function renderMetrics() {
    const bundle = state.activeSymbol ? state.bundles.get(state.activeSymbol) : null;
    if (!bundle) {
      if (state.loadingPortfolio) renderMetricsLoading();
      else renderMetricsEmpty("暂无数据");
      return;
    }
    const metrics = bundle.metrics || {};
    const rsi = toFiniteNumber(metrics.rsi14);
    const vol = toFiniteNumber(metrics.volatility_30d);
    const position = toFiniteNumber(metrics.range_position);
    const support = toFiniteNumber(metrics.support_20d);
    const resistance = toFiniteNumber(metrics.resistance_20d);
    const price = toFiniteNumber(metrics.last_close);
    const resistanceGap = price && resistance ? ((resistance - price) / price) * 100 : null;
    const rangeSub = toFiniteNumber(metrics.low_52w) !== null && toFiniteNumber(metrics.high_52w) !== null
      ? `${formatPrice(metrics.low_52w)} 至 ${formatPrice(metrics.high_52w)}`
      : "区间数据不足";
    let rsiNote = "中性区间";
    if (rsi !== null && rsi >= 70) rsiNote = "超买区间";
    else if (rsi !== null && rsi <= 30) rsiNote = "超卖区间";
    const trend = String(metrics.trend || "--");
    const trendTone = /多头|偏强/.test(trend) ? "up" : /空头|偏弱/.test(trend) ? "down" : "flat";
    const volumeRatio = toFiniteNumber(metrics.volume_ratio);
    const maxDrawdown = toFiniteNumber(metrics.max_drawdown_1y);

    $("metricsRow").setAttribute("aria-busy", "false");
    $("metricsRow").innerHTML = [
      metricCell(
        "1M 回报",
        formatPercent(metrics.return_1m),
        `3M ${formatPercent(metrics.return_3m)} · 1Y ${formatPercent(metrics.return_1y)}`,
        { tone: toneClass(metrics.return_1m) },
      ),
      metricCell("RSI14", rsi === null ? "--" : rsi.toFixed(1), `${rsiNote} · 14 日`),
      metricCell(
        "30D 波动率",
        formatPercent(vol, false),
        volumeRatio === null ? "年化标准差" : `量比 ${volumeRatio.toFixed(2)}`,
      ),
      metricCell(
        "52W 位置",
        formatPercent(position, false),
        rangeSub,
        { meter: position === null ? 0 : position },
      ),
      metricCell(
        "20D 支撑 / 阻力",
        `${formatPrice(support)} / ${formatPrice(resistance)}`,
        resistanceGap === null ? "近 20 日高低点" : `现价距阻力 ${formatPercent(resistanceGap)}`,
        { small: true },
      ),
      metricCell(
        "趋势",
        trend,
        maxDrawdown === null ? "近一年最大回撤 --" : `近一年最大回撤 ${formatPercent(maxDrawdown)}`,
        { tone: trendTone },
      ),
    ].join("");
  }

  // -------------------------------------------------------------------------
  // News
  // -------------------------------------------------------------------------

  function renderNewsLoading() {
    $("newsFilter").innerHTML = "";
    $("newsList").innerHTML = '<div class="news-skeleton"></div><div class="news-skeleton"></div><div class="news-skeleton"></div>';
    $("newsMeta").textContent = "正在汇总近 30 天新闻";
    $("newsMore").classList.add("hidden");
  }

  function renderNewsEmpty(title, body) {
    $("newsFilter").innerHTML = "";
    const host = $("newsList");
    host.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const strong = document.createElement("strong");
    strong.textContent = title;
    const span = document.createElement("span");
    span.textContent = body;
    empty.append(strong, span);
    host.appendChild(empty);
    $("newsMeta").textContent = "暂无新闻";
    $("newsMore").classList.add("hidden");
  }

  function newsSymbols(item) {
    if (Array.isArray(item.symbols) && item.symbols.length) return item.symbols;
    return item.symbol ? [item.symbol] : [];
  }

  function newsMatches(item, filter) {
    if (filter === "all") return true;
    return newsSymbols(item).includes(filter);
  }

  function renderNews() {
    if (!state.portfolio) {
      renderNewsEmpty("等待标的", "选择自选股后显示最近 30 天新闻。");
      return;
    }
    const feed = Array.isArray(state.portfolio.news_feed) ? state.portfolio.news_feed : [];
    const symbols = (state.portfolio.symbols || []).map((item) => item.symbol);
    if (state.newsFilter !== "all" && !symbols.includes(state.newsFilter)) {
      state.newsFilter = "all";
    }
    const filtered = feed.filter((item) => newsMatches(item, state.newsFilter));
    if (!feed.length) {
      renderNewsEmpty("暂无新闻", "最近 30 天没有匹配的新闻，行情数据仍然可用。");
      return;
    }

    renderNewsFilters(feed, symbols);
    if (!filtered.length) {
      $("newsList").innerHTML = "";
      const empty = document.createElement("div");
      empty.className = "empty-state";
      const strong = document.createElement("strong");
      strong.textContent = "该标的暂无新闻";
      const span = document.createElement("span");
      span.textContent = "切换到其他标的，或等待下一次新闻抓取。";
      empty.append(strong, span);
      $("newsList").appendChild(empty);
      $("newsMeta").textContent = `${state.newsFilter} · 0 条 · 最近 30 天`;
      $("newsMore").classList.add("hidden");
      return;
    }
    const visible = filtered.slice(0, state.newsLimit);
    const host = $("newsList");
    host.innerHTML = "";
    const fragment = document.createDocumentFragment();
    for (const item of visible) fragment.appendChild(createNewsItem(item));
    host.appendChild(fragment);

    const filterLabel = state.newsFilter === "all" ? `${symbols.length} 个标的` : state.newsFilter;
    $("newsMeta").textContent = `${filterLabel} · ${filtered.length} 条 · 最近 30 天`;

    const more = $("newsMore");
    if (filtered.length > state.newsLimit) {
      more.classList.remove("hidden");
      more.textContent = `加载更多（剩余 ${filtered.length - state.newsLimit} 条）`;
    } else {
      more.classList.add("hidden");
      more.textContent = "加载更多";
    }
  }

  function renderNewsFilters(feed, symbols) {
    const host = $("newsFilter");
    host.innerHTML = "";
    host.setAttribute("role", "group");
    host.setAttribute("aria-label", "新闻标的筛选");
    const entries = [
      { key: "all", label: "全部", count: feed.length },
      ...symbols.map((symbol) => ({
        key: symbol,
        label: symbol,
        count: feed.filter((item) => newsMatches(item, symbol)).length,
      })),
    ];
    for (const entry of entries) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `filter-chip${entry.key === state.newsFilter ? " is-active" : ""}`;
      button.dataset.filter = entry.key;
      button.textContent = `${entry.label} ${entry.count}`;
      button.setAttribute("aria-pressed", String(entry.key === state.newsFilter));
      host.appendChild(button);
    }
  }

  function createNewsItem(item) {
    const article = document.createElement("article");
    article.className = "news-item";

    const timeBox = document.createElement("div");
    timeBox.className = "news-time";
    const parsed = item.published_at ? new Date(item.published_at) : null;
    if (parsed && !Number.isNaN(parsed.getTime())) {
      const date = document.createElement("strong");
      date.textContent = `${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(parsed.getDate()).padStart(2, "0")}`;
      const time = document.createElement("span");
      time.textContent = `${String(parsed.getHours()).padStart(2, "0")}:${String(parsed.getMinutes()).padStart(2, "0")}`;
      timeBox.append(date, time);
    } else {
      timeBox.textContent = "时间未知";
    }

    const body = document.createElement("div");
    body.className = "news-body";
    const meta = document.createElement("div");
    meta.className = "news-meta";
    for (const symbol of newsSymbols(item)) {
      const tag = document.createElement("span");
      tag.className = "news-tag";
      tag.textContent = symbol;
      meta.appendChild(tag);
    }
    const publisher = (item.publisher || "").trim();
    if (publisher) {
      const publisherSpan = document.createElement("span");
      publisherSpan.textContent = publisher;
      meta.appendChild(publisherSpan);
    }
    if (item.source && item.source !== publisher) {
      const sourceSpan = document.createElement("span");
      sourceSpan.textContent = item.source;
      meta.appendChild(sourceSpan);
    }

    const url = safeHttpUrl(item.url);
    const title = String(item.title || "无标题");
    let titleElement;
    if (url) {
      titleElement = document.createElement("a");
      titleElement.href = url;
      titleElement.target = "_blank";
      titleElement.rel = "noopener noreferrer";
      titleElement.className = "news-title";
      titleElement.textContent = title;
      const icon = createIcon("external");
      titleElement.appendChild(icon);
    } else {
      titleElement = document.createElement("span");
      titleElement.className = "news-title";
      titleElement.textContent = title;
    }

    const summaryText = stripHtml(item.summary);
    if (summaryText) {
      const summary = document.createElement("p");
      summary.className = "news-summary";
      summary.textContent = truncateText(summaryText, 240);
      body.append(meta, titleElement, summary);
    } else {
      body.append(meta, titleElement);
    }
    article.append(timeBox, body);
    return article;
  }

  // -------------------------------------------------------------------------
  // AI panel
  // -------------------------------------------------------------------------

  function setAiBusy(busy) {
    $("aiContent").setAttribute("aria-busy", busy ? "true" : "false");
  }

  function renderAiHoldingDetail(symbol, name) {
    setAiBusy(false);
    $("aiContent").innerHTML = `
      <div class="ai-empty">
        <svg class="ai-empty-icon" aria-hidden="true"><use href="#i-spark"></use></svg>
        <h3>持仓详情 · ${escapeHtml(name || symbol || "股票")}</h3>
        <p>当前展示该持仓股票的行情、走势与新闻。如需组合研判，请将它加入自选清单并勾选。</p>
        <div class="ai-empty-rules"><span>行情详情</span><span>技术指标</span><span>近 30 天新闻</span></div>
      </div>`;
    $("aiUpdated").textContent = "持仓详情模式";
    $("aiMetaLine").textContent = "AI 生成内容不构成投资建议";
  }

  function renderAiNoSelection() {
    setAiBusy(false);
    $("aiContent").innerHTML = `
      <div class="ai-empty">
        <svg class="ai-empty-icon" aria-hidden="true"><use href="#i-spark"></use></svg>
        <h3>等待选择标的</h3>
        <p>勾选左侧自选股后，系统会自动拉取两年行情，并把近一个月价格与新闻送入模型研判。</p>
        <div class="ai-empty-rules"><span>条件式预测</span><span>新闻交叉验证</span><span>置信度标注</span></div>
      </div>`;
    $("aiUpdated").textContent = "尚未生成";
    $("aiMetaLine").textContent = "AI 生成内容不构成投资建议";
  }

  function renderAiPending(symbols) {
    setAiBusy(true);
    const list = (symbols || []).join("、");
    $("aiContent").innerHTML = `
      <div class="ai-loading">
        <div class="ai-loading-head"><span class="loader" aria-hidden="true"></span><span>正在装载行情与新闻</span></div>
        <p>${escapeHtml(list || "所选标的")} 的两年日线正在同步，完成后会自动提交 ${escapeHtml(state.config.model || DISPLAY_MODEL)} 研判。</p>
        <div class="ai-skeleton-line"></div>
        <div class="ai-skeleton-line"></div>
        <div class="ai-skeleton-line"></div>
        <div class="ai-skeleton-line"></div>
      </div>`;
    $("aiUpdated").textContent = "准备研判";
    $("aiMetaLine").textContent = "AI 生成内容不构成投资建议";
  }

  function renderAiWaitingForAnalysis() {
    setAiBusy(false);
    $("aiContent").innerHTML = `
      <div class="ai-empty">
        <svg class="ai-empty-icon" aria-hidden="true"><use href="#i-spark"></use></svg>
        <h3>行情已就绪</h3>
        <p>点击“立即研判”，或重新勾选标的以自动生成组合分析。</p>
        <div class="ai-empty-rules"><span>条件式预测</span><span>新闻交叉验证</span><span>置信度标注</span></div>
      </div>`;
    $("aiUpdated").textContent = "等待研判";
  }

  function renderAiConfigured() {
    setAiBusy(false);
    $("aiContent").innerHTML = `
      <div class="ai-empty">
        <svg class="ai-empty-icon" aria-hidden="true"><use href="#i-spark"></use></svg>
        <h3>未配置模型密钥</h3>
        <p>在项目根目录的 .env 中填写模型 API Key，重启服务后即可启用研判。密钥只保存在服务端。</p>
        <div class="ai-empty-rules"><span>行情可用</span><span>图表可用</span><span>研判待启用</span></div>
      </div>`;
    $("aiUpdated").textContent = "模型未配置";
    $("aiMetaLine").textContent = "AI 生成内容不构成投资建议";
  }

  function renderAiLoading(symbols) {
    setAiBusy(true);
    const list = (symbols || []).join("、");
    $("aiContent").innerHTML = `
      <div class="ai-loading">
        <div class="ai-loading-head"><span class="loader" aria-hidden="true"></span><span>${escapeHtml(state.config.model || DISPLAY_MODEL)} 正在推理</span></div>
        <p>已提交 ${escapeHtml(list || "所选标的")} 的价格、技术指标与近 30 天新闻。推理通常需要 15 至 60 秒，请勿关闭页面。</p>
        <div class="ai-loading-meta">
          <div><span>标 的</span><strong>${(symbols || []).length} 个</strong></div>
          <div><span>新闻窗口</span><strong>30 天</strong></div>
          <div><span>日线范围</span><strong>2 年</strong></div>
        </div>
        <div class="ai-skeleton-line"></div>
        <div class="ai-skeleton-line"></div>
        <div class="ai-skeleton-line"></div>
        <div class="ai-skeleton-line"></div>
        <div class="ai-skeleton-line"></div>
      </div>`;
  }

  function renderAiError(message, retryKind = "ai") {
    setAiBusy(false);
    const retryLabel = retryKind === "portfolio" ? "重新加载行情" : "重新研判";
    $("aiContent").innerHTML = `
      <div class="ai-error">
        <div class="ai-error-box">
          <h3>研判暂未完成</h3>
          <p>${escapeHtml(message || "未知错误，请稍后重试。")}</p>
        </div>
        <button class="btn btn-ghost" type="button" data-retry="${retryKind === "portfolio" ? "portfolio" : "ai"}">${ICON.refresh}${retryLabel}</button>
      </div>`;
    $("aiUpdated").textContent = "研判失败";
    $("aiMetaLine").textContent = "AI 生成内容不构成投资建议";
  }

  function startAnalysisTimer() {
    stopAnalysisTimer();
    state.analysisStartedAt = Date.now();
    $("aiUpdated").textContent = "研判中 · 0s";
    state.analysisTimer = window.setInterval(() => {
      const seconds = Math.floor((Date.now() - state.analysisStartedAt) / 1000);
      $("aiUpdated").textContent = `研判中 · ${seconds}s`;
    }, 1000);
  }

  function stopAnalysisTimer() {
    if (state.analysisTimer) {
      window.clearInterval(state.analysisTimer);
      state.analysisTimer = null;
    }
  }

  function abortAnalysisRequest() {
    if (state.analysisController) {
      state.analysisController.abort();
      state.analysisController = null;
    }
  }

  async function runAnalysis({ force = false, manual = false } = {}) {
    if (state.detailSymbol) {
      toast("持仓详情模式下请从自选清单发起研判");
      return false;
    }
    if (!state.selected.length) {
      toast("请先选择标的");
      return false;
    }
    if (!state.config.ai_configured) {
      renderAiConfigured();
      return false;
    }
    if (!state.portfolio || state.loadingPortfolio) {
      if (manual) toast("行情仍在加载，请稍后");
      return false;
    }
    const requested = [...state.selected];
    const signature = selectedSignature(requested);
    const seq = ++state.analysisSeq;
    abortAnalysisRequest();
    const controller = new AbortController();
    state.analysisController = controller;
    state.aiState = "loading";
    state.analysisPayload = null;
    setAnalysisState("running", "AI 研判中");
    renderAiLoading(requested);
    startAnalysisTimer();
    updateActionStates();

    try {
      const payload = await apiJson("/api/analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbols: requested,
          refresh: false,
          force,
          platform: state.platform,
        }),
        signal: controller.signal,
      });
      if (seq !== state.analysisSeq || selectedSignature() !== signature) return false;
      state.analysisController = null;
      state.aiState = "ready";
      state.analysisPayload = payload;
      stopAnalysisTimer();
      renderAiReady(payload);
      setAnalysisState("ready", "研判完成");
      updateActionStates();
      if (manual) toast(payload.cached ? "已读取缓存的研判结果" : "研判完成");
      return true;
    } catch (error) {
      if (isAbortError(error)) return false;
      if (seq !== state.analysisSeq) return false;
      state.analysisController = null;
      state.aiState = "error";
      stopAnalysisTimer();
      const message = publicAiMessage(error.message || "研判失败，请稍后重试");
      renderAiError(message, state.portfolio ? "ai" : "portfolio");
      setAnalysisState("error", "研判失败");
      updateActionStates();
      toast(message, "error");
      return false;
    }
  }

  function stanceClass(stance) {
    if (stance === "偏多") return "bullish";
    if (stance === "偏空") return "bearish";
    return "neutral";
  }

  function regimeInfo(regime) {
    if (regime === "risk-on") return { className: "is-on", label: "RISK-ON · 风险偏好" };
    if (regime === "risk-off") return { className: "is-off", label: "RISK-OFF · 风险规避" };
    return { className: "is-neutral", label: "NEUTRAL · 中性环境" };
  }

  function formatGeneratedAt(value) {
    if (!value) return "时间未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "时间未知";
    return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  }

  function renderAiReady(payload) {
    setAiBusy(false);
    const analysis = (payload && payload.analysis) || {};
    const meta = (payload && payload.meta) || analysis.meta || {};
    const portfolioMeta = (payload && payload.portfolio_meta) || {};
    const cached = Boolean(payload && payload.cached);
    const regime = regimeInfo(analysis.market_regime);
    const stance = analysis.portfolio_stance || "中性";
    const stanceTone = stanceClass(stance);
    const confidence = Math.max(0, Math.min(100, Number(analysis.confidence) || 0));
    const themes = Array.isArray(analysis.key_themes) ? analysis.key_themes : [];
    const symbols = Array.isArray(analysis.symbols) ? analysis.symbols : [];
    const risks = Array.isArray(analysis.portfolio_risks) ? analysis.portfolio_risks : [];
    const watchItems = Array.isArray(analysis.watch_items) ? analysis.watch_items : [];
    const generated = formatGeneratedAt(meta.generated_at);
    const asOf = portfolioMeta.data_as_of || "";
    const usage = meta.usage || {};

    const themesHtml = themes
      .map((theme) => `<span class="theme-chip">${escapeHtml(theme)}</span>`)
      .join("");

    const symbolHtml = symbols
      .map((item) => {
        const tone = stanceClass(item.stance);
        const itemConfidence = Math.max(0, Math.min(100, Number(item.confidence) || 0));
        const newsTone = item.news_signal === "正面" ? "up" : item.news_signal === "负面" ? "down" : "flat";
        const base = item.base_case || { range: "数据不足", note: "" };
        const bull = item.bull_case || { range: "数据不足", note: "" };
        const bear = item.bear_case || { range: "数据不足", note: "" };
        const catalysts = Array.isArray(item.catalysts) ? item.catalysts : [];
        const itemRisks = Array.isArray(item.risks) ? item.risks : [];
        const catalystsHtml = catalysts.length
          ? catalysts.map((entry) => `<li>${escapeHtml(entry)}</li>`).join("")
          : "<li>模型未提供</li>";
        const risksHtml = itemRisks.length
          ? itemRisks.map((entry) => `<li>${escapeHtml(entry)}</li>`).join("")
          : "<li>模型未提供</li>";
        return `
          <div class="ai-symbol-row is-${tone}">
            <div class="ai-symbol-top">
              <div>
                <span class="ai-symbol-name">${escapeHtml(item.symbol)}<small>${escapeHtml(item.name || "")}</small></span>
              </div>
              <div style="display:flex;align-items:center;gap:8px">
                <span class="ai-symbol-confidence">${itemConfidence}%</span>
                <span class="stance-badge is-${tone}">${escapeHtml(item.stance || "中性")}</span>
              </div>
            </div>
            <p class="ai-thesis">${escapeHtml(item.thesis || "模型未提供核心判断。")}</p>
            <div class="level-row">
              <div class="level-cell"><span class="level-label">支撑位</span><span class="level-value">${escapeHtml(formatPrice(item.support))}</span></div>
              <div class="level-cell"><span class="level-label">阻力位</span><span class="level-value">${escapeHtml(formatPrice(item.resistance))}</span></div>
              <div class="level-cell"><span class="level-label">新闻信号</span><span class="level-value ${newsTone}">${escapeHtml(item.news_signal || "中性")}</span></div>
            </div>
            <div class="scenario-list">
              <div class="scenario-row"><span class="scenario-label">基准</span><span class="scenario-range">${escapeHtml(base.range)}</span><span class="scenario-note">${escapeHtml(base.note)}</span></div>
              <div class="scenario-row"><span class="scenario-label">上行</span><span class="scenario-range up">${escapeHtml(bull.range)}</span><span class="scenario-note">${escapeHtml(bull.note)}</span></div>
              <div class="scenario-row"><span class="scenario-label">下行</span><span class="scenario-range down">${escapeHtml(bear.range)}</span><span class="scenario-note">${escapeHtml(bear.note)}</span></div>
            </div>
            <details class="ai-details">
              <summary>${ICON.chevron}展开依据、催化与风险</summary>
              <div class="ai-read"><strong>技术面</strong>${escapeHtml(item.technical_read || "数据不足。")}</div>
              <div class="ai-read"><strong>新闻面</strong>${escapeHtml(item.news_read || "数据不足。")}</div>
              <div class="ai-detail-grid">
                <div><h4>潜在催化</h4><ul>${catalystsHtml}</ul></div>
                <div><h4>主要风险</h4><ul>${risksHtml}</ul></div>
              </div>
            </details>
          </div>`;
      })
      .join("");

    const risksHtml = risks.length
      ? risks.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
      : "<li>模型未提供</li>";
    const watchHtml = watchItems.length
      ? watchItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
      : "<li>模型未提供</li>";
    const usageText = usage.total_tokens
      ? `${Number(usage.prompt_tokens || 0).toLocaleString("en-US")} / ${Number(usage.completion_tokens || 0).toLocaleString("en-US")} tok`
      : "token 用量未知";
    const model = state.config.model || DISPLAY_MODEL;

    $("aiContent").innerHTML = `
      <div class="ai-result">
        <div class="ai-regime">
          <span class="regime-tag ${regime.className}">${regime.label}</span>
          <span class="ai-time">${escapeHtml(generated)}</span>
        </div>
        <div class="ai-verdict">
          <div>
            <span class="ai-verdict-label">组合立场</span>
            <span class="ai-verdict-value is-${stanceTone}">${escapeHtml(stance)}</span>
          </div>
          <div class="ai-confidence">
            <div class="confidence-value">${confidence}<span>%</span></div>
            <div class="confidence-track"><div class="confidence-fill" style="width:${confidence}%"></div></div>
          </div>
        </div>
        <p class="ai-summary">${escapeHtml(analysis.summary || "模型未提供组合摘要。")}</p>
        <div class="ai-themes">${themesHtml}</div>
        <div class="ai-section">
          <div class="ai-section-head"><span>标的研判</span><span>${symbols.length} 个</span></div>
          ${symbolHtml}
        </div>
        <div class="ai-bottom-list"><h4>组合风险</h4><ul>${risksHtml}</ul></div>
        <div class="ai-bottom-list"><h4>接下来关注</h4><ul>${watchHtml}</ul></div>
      </div>`;

    $("aiUpdated").textContent = `${cached ? "缓存 · " : ""}${generated}`;
    $("aiMetaLine").textContent = `${model} · ${usageText}${asOf ? ` · 数据截至 ${asOf}` : ""} · 不构成投资建议`;
  }

  // -------------------------------------------------------------------------
  // Events
  // -------------------------------------------------------------------------

  function setRailCollapsed(toggleId, bodyId, collapsed) {
    const toggle = $(toggleId);
    const body = $(bodyId);
    if (!toggle || !body) return;
    toggle.classList.toggle("is-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    body.classList.toggle("is-collapsed", collapsed);
  }

  function bindRailToggle(toggleId, bodyId) {
    const toggle = $(toggleId);
    const body = $(bodyId);
    if (!toggle || !body) return;
    const toggleState = () => {
      const nextCollapsed = !body.classList.contains("is-collapsed");
      setRailCollapsed(toggleId, bodyId, nextCollapsed);
      if (!nextCollapsed) {
        window.requestAnimationFrame(() => {
          body.scrollIntoView({
            block: "nearest",
            behavior: REDUCED_MOTION ? "auto" : "smooth",
          });
        });
      }
    };
    toggle.addEventListener("click", toggleState);
    toggle.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleState();
      }
    });
    setRailCollapsed(toggleId, bodyId, body.classList.contains("is-collapsed"));
  }

  function bindEvents() {
    bindSearch();
    const platformSwitch = $("platformSwitch");
    if (platformSwitch) {
      platformSwitch.addEventListener("click", (event) => {
        const button = event.target.closest(".platform-btn");
        if (!button || !platformSwitch.contains(button)) return;
        void switchPlatform(button.dataset.platform);
      });
    }
    bindRailToggle("watchToggle", "watchBody");
    bindRailToggle("screenerToggle", "screenerBody");
    bindRailToggle("positionsToggle", "positionBody");
    bindRailToggle("aiWatchToggle", "aiWatchBody");

    const aiWatchSwitch = $("aiWatchSwitch");
    if (aiWatchSwitch) {
      aiWatchSwitch.addEventListener("change", () => {
        setAiWatchEnabled(aiWatchSwitch.checked);
      });
    }
    const aiWatchStrategy = $("aiWatchStrategy");
    if (aiWatchStrategy) {
      aiWatchStrategy.addEventListener("input", () => {
        state.aiWatchStrategy = Math.max(
          0,
          Math.min(100, Math.round(Number(aiWatchStrategy.value) || 0))
        );
        const label = $("aiWatchStrategyLabel");
        if (label) label.textContent = aiWatchStrategyLabel(state.aiWatchStrategy);
      });
      aiWatchStrategy.addEventListener("change", () => {
        persistAiWatchSettings();
        if (state.aiWatchEnabled) void setAiWatchEnabled(true);
      });
    }

    const logoutBtn = $("logoutBtn");
    if (logoutBtn) {
      logoutBtn.addEventListener("click", async () => {
        logoutBtn.disabled = true;
        try {
          await apiJson("/api/auth/logout", { method: "POST" });
        } catch (error) {
          /* clear the local view regardless */
        }
        window.location.replace("/login");
      });
    }

    $("refreshAll").addEventListener("click", async () => {
      if (state.refreshBusy) return;
      state.refreshBusy = true;
      const button = $("refreshAll");
      button.classList.add("is-spinning");
      button.disabled = true;
      try {
        await refreshAllQuotes(true);
        if (state.detailSymbol) {
          const ok = await openHoldingDetail(state.detailSymbol, { refresh: true });
          if (ok) toast("持仓详情已刷新");
        } else if (state.selected.length) {
          const ok = await loadPortfolio({ refresh: true, autoAnalyze: true });
          if (ok) toast("行情与研判已刷新");
        } else {
          toast("行情已刷新");
        }
      } finally {
        state.refreshBusy = false;
        button.classList.remove("is-spinning");
        button.disabled = false;
      }
    });

    $("refreshSelection").addEventListener("click", async () => {
      if (state.detailSymbol) {
        const ok = await openHoldingDetail(state.detailSymbol, { refresh: true });
        if (ok) toast("持仓详情已刷新");
        return;
      }
      if (!state.selected.length) {
        toast("请先选择标的");
        return;
      }
      const ok = await loadPortfolio({ refresh: true, autoAnalyze: true });
      if (ok) toast("所选标的数据已刷新");
    });

    $("analyzeBtn").addEventListener("click", () => {
      if (!state.selected.length) {
        toast("请先选择标的");
        return;
      }
      if (state.loadingPortfolio || !state.portfolio) {
        toast("行情仍在加载，请稍后");
        return;
      }
      void runAnalysis({ force: true, manual: true });
    });

    $("reanalyzeBtn").addEventListener("click", () => {
      void runAnalysis({ force: true, manual: true });
    });

    $("watchList").addEventListener("click", (event) => {
      const row = event.target.closest(".watch-row");
      if (!row) return;
      const symbol = row.dataset.symbol;
      if (event.target.closest(".watch-remove")) {
        event.stopPropagation();
        removeWatchSymbol(symbol);
        return;
      }
      toggleSelection(symbol);
    });

    $("watchList").addEventListener("keydown", (event) => {
      const row = event.target.closest(".watch-row");
      if (!row) return;
      if (event.key === " " || event.key === "Enter") {
        event.preventDefault();
        toggleSelection(row.dataset.symbol);
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        removeWatchSymbol(row.dataset.symbol);
      }
    });

    const positionList = $("positionList");
    if (positionList) {
      const openDetail = (event) => {
        const item = event.target.closest(".position-item[data-symbol]");
        if (!item) return;
        void openHoldingDetail(item.dataset.symbol, { name: item.dataset.name || "" });
      };
      positionList.addEventListener("click", openDetail);
      positionList.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const item = event.target.closest(".position-item[data-symbol]");
        if (!item) return;
        event.preventDefault();
        void openHoldingDetail(item.dataset.symbol, { name: item.dataset.name || "" });
      });
    }

    $("queueChips").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-symbol]");
      if (!button) return;
      toggleSelection(button.dataset.symbol);
    });

    $("screenBtn").addEventListener("click", () => {
      void runScreener();
    });

    $("capitalInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void runScreener();
      }
    });

    $("autoTradeBtn").addEventListener("click", () => {
      void runAutoTrade();
    });

    const closePositionBtn = $("closePositionBtn");
    if (closePositionBtn) {
      closePositionBtn.addEventListener("click", openClosePositionModal);
    }
    const partialSellBtn = $("partialSellBtn");
    if (partialSellBtn) {
      partialSellBtn.addEventListener("click", openPartialSellModal);
    }
    const partialSellShares = $("partialSellShares");
    if (partialSellShares) {
      partialSellShares.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        openPartialSellModal();
      });
    }
    const closePositionCancel = $("closePositionCancel");
    if (closePositionCancel) {
      closePositionCancel.addEventListener("click", closeClosePositionModal);
    }
    const closePositionConfirm = $("closePositionConfirm");
    if (closePositionConfirm) {
      closePositionConfirm.addEventListener("click", () => {
        void confirmClosePosition();
      });
    }
    const closePositionModal = $("closePositionModal");
    if (closePositionModal) {
      closePositionModal.addEventListener("click", (event) => {
        if (event.target === closePositionModal) closeClosePositionModal();
      });
    }

    const manualBuyBtn = $("manualBuyBtn");
    if (manualBuyBtn) {
      manualBuyBtn.addEventListener("click", openManualBuyModal);
    }
    const manualBuyList = $("manualBuyList");
    if (manualBuyList) {
      manualBuyList.addEventListener("input", () => {
        updateManualBuySummary();
      });
    }
    const manualBuyCancel = $("manualBuyCancel");
    if (manualBuyCancel) {
      manualBuyCancel.addEventListener("click", closeManualBuyModal);
    }
    const manualBuyConfirm = $("manualBuyConfirm");
    if (manualBuyConfirm) {
      manualBuyConfirm.addEventListener("click", () => {
        void confirmManualBuy();
      });
    }
    const manualBuyModal = $("manualBuyModal");
    if (manualBuyModal) {
      manualBuyModal.addEventListener("click", (event) => {
        if (event.target === manualBuyModal) closeManualBuyModal();
      });
    }

    const rechargeBtn = $("rechargeBtn");
    if (rechargeBtn) {
      rechargeBtn.addEventListener("click", () => openContactModal("充值"));
    }
    const withdrawBtn = $("withdrawBtn");
    if (withdrawBtn) {
      withdrawBtn.addEventListener("click", () => openContactModal("提现"));
    }
    const contactClose = $("contactClose");
    if (contactClose) {
      contactClose.addEventListener("click", closeContactModal);
    }
    const contactModal = $("contactModal");
    if (contactModal) {
      contactModal.addEventListener("click", (event) => {
        if (event.target === contactModal) closeContactModal();
      });
    }

    $("screenerResult").addEventListener("click", (event) => {
      const row = event.target.closest(".screener-pick");
      if (!row) return;
      const symbol = row.dataset.symbol;
      if (symbol && state.bundles.has(symbol)) activateSymbol(symbol);
    });

    $("screenerResult").addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const row = event.target.closest(".screener-pick");
      if (!row) return;
      event.preventDefault();
      if (state.bundles.has(row.dataset.symbol)) activateSymbol(row.dataset.symbol);
    });

    $("symbolTabs").addEventListener("click", (event) => {
      const button = event.target.closest(".symbol-tab");
      if (button) activateSymbol(button.dataset.symbol, true);
    });

    $("symbolTabs").addEventListener("keydown", (event) => {
      const buttons = [...$("symbolTabs").querySelectorAll(".symbol-tab")];
      if (!buttons.length) return;
      const current = buttons.indexOf(document.activeElement);
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const direction = event.key === "ArrowRight" ? 1 : -1;
        const next = (Math.max(0, current) + direction + buttons.length) % buttons.length;
        activateSymbol(buttons[next].dataset.symbol, true);
      } else if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        const next = event.key === "Home" ? 0 : buttons.length - 1;
        activateSymbol(buttons[next].dataset.symbol, true);
      }
    });

    $("rangeSwitch").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-range]");
      if (!button) return;
      const range = button.dataset.range;
      if (!(range in RANGE_LABELS)) return;
      const wasIntraday = isIntradayRange(state.range);
      state.range = range;
      $("rangeSwitch").querySelectorAll("button").forEach((item) => {
        item.classList.toggle("is-active", item === button);
      });
      if (isIntradayRange(range) && !wasIntraday) {
        state.mode = "line";
        $("chartModeSwitch").querySelectorAll("button").forEach((item) => {
          item.classList.toggle("is-active", item.dataset.mode === "line");
        });
      }
      renderChart();
    });

    $("chartModeSwitch").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-mode]");
      if (!button) return;
      const mode = button.dataset.mode;
      if (mode !== "candle" && mode !== "line") return;
      state.mode = mode;
      $("chartModeSwitch").querySelectorAll("button").forEach((item) => {
        item.classList.toggle("is-active", item === button);
      });
      renderChart();
    });

    $("toggleTable").addEventListener("click", () => {
      const wrapper = $("dataTableWrap");
      const open = wrapper.classList.toggle("hidden") === false;
      $("toggleTable").setAttribute("aria-expanded", String(open));
      $("toggleTable").textContent = open ? "收起数据表" : "查看数据表";
      if (open) renderDataTable(currentChartData(), true);
    });

    $("newsFilter").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-filter]");
      if (!button) return;
      state.newsFilter = button.dataset.filter;
      state.newsLimit = 8;
      renderNews();
    });

    $("newsMore").addEventListener("click", () => {
      state.newsLimit += 8;
      renderNews();
    });

    $("aiContent").addEventListener("click", (event) => {
      const button = event.target.closest("[data-retry]");
      if (!button) return;
      if (button.dataset.retry === "portfolio") {
        void loadPortfolio({ refresh: false, autoAnalyze: true });
      } else {
        void runAnalysis({ force: true, manual: true });
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey) {
        const target = event.target;
        const tag = target && target.tagName ? target.tagName.toLowerCase() : "";
        if (tag === "input" || tag === "textarea" || (target && target.isContentEditable)) return;
        event.preventDefault();
        setRailCollapsed("watchToggle", "watchBody", false);
        $("stockSearch").focus();
        $("stockSearch").select();
      }
      if (event.key === "Escape") {
        closeSearch();
        closeContactModal();
        closeClosePositionModal();
        closeManualBuyModal();
      }
    });

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && Date.now() - state.lastQuoteFetch > 15000) {
        void refreshAllQuotes(false);
      }
    });

    window.setInterval(() => {
      if (document.hidden) return;
      void refreshAllQuotes(false);
    }, POLL_MS);

    window.setInterval(() => {
      if (document.hidden) return;
      void loadAccountSummary();
    }, 60000);

    if (state.intradayTimer) window.clearInterval(state.intradayTimer);
    state.intradayTimer = window.setInterval(() => {
      if (document.hidden || !state.activeSymbol) return;
      if (!isTradingSession()) return;
      void fetchActiveQuote();
      if (state.range === "DAY") {
        ensureIntraday(state.activeSymbol, "DAY", { refresh: true });
      } else if (state.range === "WEEK") {
        const now = Date.now();
        if (now - state.lastWeekLiveAt >= 15000) {
          state.lastWeekLiveAt = now;
          ensureIntraday(state.activeSymbol, "WEEK", { refresh: true });
        }
      }
    }, 5000);
  }

  function startClock() {
    const tick = () => {
      const now = new Date();
      $("clock").textContent = [now.getHours(), now.getMinutes(), now.getSeconds()]
        .map((value) => String(value).padStart(2, "0"))
        .join(":");
    };
    tick();
    window.setInterval(tick, 1000);
  }

  function formatLocalTime(value) {
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) return "--:--:--";
    return [date.getHours(), date.getMinutes(), date.getSeconds()]
      .map((part) => String(part).padStart(2, "0"))
      .join(":");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
