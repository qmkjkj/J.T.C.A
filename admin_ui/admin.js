(function () {
  "use strict";

  const loginView = document.getElementById("adminLoginView");
  const appView = document.getElementById("adminApp");
  const loginForm = document.getElementById("adminLoginForm");
  const loginError = document.getElementById("adminLoginError");
  const loginBtn = document.getElementById("adminLoginBtn");
  const adminWho = document.getElementById("adminWho");
  const logoutBtn = document.getElementById("adminLogout");
  const toastEl = document.getElementById("toast");

  const state = {
    view: "overview",
    usersPage: 1,
    usersQuery: "",
    loginsPage: 1,
    onlyFailed: false,
    screensPage: 1,
    tradesPage: 1,
    loaded: {},
  };

  const PAGE_SIZE = 20;
  const VIP_NAMES = { 0: "普通用户", 1: "黄金VIP", 2: "白金VIP", 3: "钻石VIP" };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function pad(value) {
    return value < 10 ? "0" + value : String(value);
  }

  function formatTime(raw) {
    if (!raw) return "—";
    const text = String(raw);
    const match = text.match(
      /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/
    );
    if (!match) return text;
    return (
      match[1] + "-" + match[2] + "-" + match[3] + " " + match[4] + ":" + match[5]
    );
  }

  let toastTimer = 0;
  function toast(message, isError) {
    toastEl.textContent = message;
    toastEl.classList.toggle("is-error", !!isError);
    toastEl.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toastEl.classList.remove("is-visible");
    }, 2600);
  }

  async function api(path, options) {
    const response = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...(options || {}),
    });
    let data = null;
    try {
      data = await response.json();
    } catch (err) {
      data = null;
    }
    if (response.status === 401 && !path.endsWith("/login")) {
      showLoginView();
    }
    if (!response.ok) {
      const detail = data && (data.detail || data.message);
      let message = "请求失败，请稍后重试";
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail) && detail.length) {
        message = detail[0].msg || message;
      }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return data || {};
  }

  function emptyRow(tbody, columns, text) {
    tbody.replaceChildren();
    const tr = el("tr", "empty-row");
    const td = el("td", null, text);
    td.colSpan = columns;
    tr.appendChild(td);
    tbody.appendChild(tr);
  }

  function showLoginView() {
    appView.classList.add("hidden");
    loginView.classList.remove("hidden");
    document.getElementById("adminPassword").value = "";
    loginError.classList.add("hidden");
    document.getElementById("adminUsername").focus();
  }

  function showApp(username) {
    loginView.classList.add("hidden");
    appView.classList.remove("hidden");
    adminWho.textContent = username ? username + " · 管理员" : "管理员";
    state.loaded = {};
    switchView("overview", true);
  }

  function setLoginBusy(value) {
    loginBtn.disabled = value;
    loginBtn.textContent = value ? "验证中…" : "进入后台";
  }

  loginForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    const username = document.getElementById("adminUsername").value.trim();
    const password = document.getElementById("adminPassword").value;
    if (!username || !password) {
      loginError.textContent = "请输入后台账号和密码";
      loginError.classList.remove("hidden");
      return;
    }
    loginError.classList.add("hidden");
    setLoginBusy(true);
    try {
      const data = await api("/api/admin/login", {
        method: "POST",
        body: JSON.stringify({ username: username, password: password }),
      });
      showApp(data.admin && data.admin.username);
    } catch (err) {
      loginError.textContent = err.message || "登录失败";
      loginError.classList.remove("hidden");
    } finally {
      setLoginBusy(false);
    }
  });

  logoutBtn.addEventListener("click", async function () {
    try {
      await api("/api/admin/logout", { method: "POST" });
    } catch (err) {
      /* ignore */
    }
    showLoginView();
  });

  const navButtons = Array.from(document.querySelectorAll(".admin-nav button"));
  navButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      switchView(button.dataset.view);
    });
  });

  function switchView(view, force) {
    state.view = view;
    navButtons.forEach(function (button) {
      button.classList.toggle("is-active", button.dataset.view === view);
    });
    document.querySelectorAll(".admin-view").forEach(function (section) {
      section.classList.toggle("hidden", section.id !== "view-" + view);
    });
    if (force || !state.loaded[view]) {
      state.loaded[view] = true;
      if (view === "overview") loadOverview();
      if (view === "users") loadUsers(state.usersPage);
      if (view === "logins") loadLogins(state.loginsPage);
      if (view === "screens") loadScreens(state.screensPage);
      if (view === "trades") loadTrades(state.tradesPage);
    }
  }

  /* ---------- Overview ---------- */

  function statCard(label, value, sub) {
    const card = el("div", "stat-card");
    card.appendChild(el("div", "stat-label", label));
    card.appendChild(el("div", "stat-value", value));
    if (sub) card.appendChild(el("div", "stat-sub", sub));
    return card;
  }

  async function loadOverview() {
    const grid = document.getElementById("statGrid");
    try {
      const data = await api("/api/admin/overview");
      const tradeInfo = data.trades || { count: 0, cost: 0, profit: 0 };
      grid.replaceChildren(
        statCard("用户总数", data.users.total, "启用 " + data.users.active + " 人"),
        statCard("在线会话", data.sessions.active, "7 天内有效"),
        statCard("登录成功", data.logins.success, "失败 " + data.logins.failed + " 次"),
        statCard("选股次数", data.screens.runs, "累计资金 ¥" + Math.round(data.screens.capital).toLocaleString("zh-CN")),
        statCard(
          "自动交易",
          tradeInfo.count,
          "投入 ¥" + Math.round(tradeInfo.cost).toLocaleString("zh-CN") +
            " · 收益 ¥" + Number(tradeInfo.profit || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 })
        )
      );
      renderRecentLogins(data.recent_logins || []);
    } catch (err) {
      grid.replaceChildren(el("div", "admin-loading", err.message || "读取失败"));
      if (err.status !== 401) toast(err.message || "读取概览失败", true);
    }
  }

  function resultTag(success) {
    return el("span", "tag " + (success ? "ok" : "bad"), success ? "成功" : "失败");
  }

  function renderRecentLogins(rows) {
    const tbody = document.getElementById("recentLogins");
    if (!rows.length) {
      emptyRow(tbody, 5, "暂无登录记录");
      return;
    }
    tbody.replaceChildren();
    rows.forEach(function (row) {
      const tr = el("tr");
      tr.appendChild(el("td", null, row.username || "—"));
      tr.appendChild(el("td", "mono", row.ip || "—"));
      const resultCell = el("td");
      resultCell.appendChild(resultTag(!!row.success));
      tr.appendChild(resultCell);
      tr.appendChild(el("td", null, row.message || "—"));
      tr.appendChild(el("td", "mono", formatTime(row.created_at)));
      tbody.appendChild(tr);
    });
  }

  /* ---------- Users ---------- */

  async function loadUsers(page) {
    state.usersPage = page;
    const tbody = document.getElementById("usersBody");
    try {
      const query = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (state.usersQuery) query.set("q", state.usersQuery);
      const data = await api("/api/admin/users?" + query.toString());
      renderUsers(data.items || []);
      updatePager("users", page, data.total, PAGE_SIZE);
    } catch (err) {
      emptyRow(tbody, 10, err.message || "读取失败");
      if (err.status !== 401) toast(err.message || "读取用户失败", true);
    }
  }

  function renderUsers(rows) {
    const tbody = document.getElementById("usersBody");
    if (!rows.length) {
      emptyRow(tbody, 10, "暂无用户");
      return;
    }
    tbody.replaceChildren();
    rows.forEach(function (row) {
      const tr = el("tr");
      tr.appendChild(el("td", "mono", row.id));
      tr.appendChild(el("td", null, row.username));

      const vipCell = el("td");
      const vipSelect = document.createElement("select");
      const level = Math.max(0, Math.min(3, Number(row.vip_level) || 0));
      vipSelect.className = "vip-select vip-" + level;
      vipSelect.setAttribute("aria-label", "设置会员等级");
      [0, 1, 2, 3].forEach(function (value) {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = VIP_NAMES[value];
        if (value === level) option.selected = true;
        vipSelect.appendChild(option);
      });
      vipSelect.addEventListener("change", function () {
        setUserVip(row.id, Number(vipSelect.value), vipSelect);
      });
      vipCell.appendChild(vipSelect);
      tr.appendChild(vipCell);

      const balanceCell = el("td");
      const balanceWrap = el("div", "balance-cell");
      const balanceInput = document.createElement("input");
      balanceInput.type = "number";
      balanceInput.min = "0";
      balanceInput.step = "0.01";
      balanceInput.className = "balance-input";
      balanceInput.value = Number(row.balance || 0).toFixed(2);
      balanceInput.setAttribute("aria-label", "账户余额");
      const balanceSave = el("button", "btn btn-ghost btn-sm", "保存");
      balanceSave.type = "button";
      balanceSave.addEventListener("click", function () {
        setUserBalance(row.id, balanceInput.value, balanceSave);
      });
      balanceInput.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          setUserBalance(row.id, balanceInput.value, balanceSave);
        }
      });
      balanceWrap.appendChild(balanceInput);
      balanceWrap.appendChild(balanceSave);
      balanceCell.appendChild(balanceWrap);
      tr.appendChild(balanceCell);

      const modeCell = el("td");
      const modeSelect = document.createElement("select");
      modeSelect.className = "mode-select";
      modeSelect.setAttribute("aria-label", "账号类型");
      [
        { value: 1, label: "模拟交易账号" },
        { value: 0, label: "真实交易账号" },
      ].forEach(function (option) {
        const node = document.createElement("option");
        node.value = String(option.value);
        node.textContent = option.label;
        if (Number(row.is_simulated) === option.value) node.selected = true;
        modeSelect.appendChild(node);
      });
      modeSelect.addEventListener("change", function () {
        setUserMode(row.id, Number(modeSelect.value), modeSelect);
      });
      modeCell.appendChild(modeSelect);
      tr.appendChild(modeCell);

      const statusCell = el("td");
      statusCell.appendChild(
        el("span", "tag " + (row.status === 1 ? "ok" : "bad"), row.status === 1 ? "启用" : "停用")
      );
      tr.appendChild(statusCell);

      tr.appendChild(el("td", "mono", row.active_sessions || 0));
      tr.appendChild(el("td", "mono", formatTime(row.created_at)));
      tr.appendChild(el("td", "mono", formatTime(row.last_login_at)));

      const actions = el("td");
      const toggle = el("button", "btn btn-ghost btn-sm", row.status === 1 ? "停用" : "启用");
      toggle.type = "button";
      toggle.addEventListener("click", function () {
        setUserStatus(row.id, row.status === 1 ? 0 : 1, toggle);
      });
      const remove = el("button", "btn btn-danger btn-sm", "删除");
      remove.type = "button";
      remove.style.marginLeft = "6px";
      remove.addEventListener("click", function () {
        deleteUser(row.id, row.username);
      });
      actions.appendChild(toggle);
      actions.appendChild(remove);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
  }

  async function setUserStatus(userId, status, button) {
    button.disabled = true;
    try {
      await api("/api/admin/users/" + userId + "/status", {
        method: "POST",
        body: JSON.stringify({ status: status }),
      });
      toast(status === 1 ? "用户已启用" : "用户已停用");
      loadUsers(state.usersPage);
    } catch (err) {
      toast(err.message || "操作失败", true);
      button.disabled = false;
    }
  }

  async function setUserVip(userId, level, select) {
    select.disabled = true;
    try {
      const data = await api("/api/admin/users/" + userId + "/vip", {
        method: "POST",
        body: JSON.stringify({ vip_level: level }),
      });
      select.className = "vip-select vip-" + level;
      toast("会员等级已调整为 " + (data.vip_name || VIP_NAMES[level]));
    } catch (err) {
      toast(err.message || "调整会员等级失败", true);
      loadUsers(state.usersPage);
    } finally {
      select.disabled = false;
    }
  }

  async function setUserBalance(userId, rawValue, button) {
    const value = Number(rawValue);
    if (!Number.isFinite(value) || value < 0) {
      toast("余额需为不小于 0 的数字", true);
      return;
    }
    button.disabled = true;
    try {
      const data = await api("/api/admin/users/" + userId + "/balance", {
        method: "POST",
        body: JSON.stringify({ balance: value }),
      });
      toast("账户余额已更新为 ¥" + Number(data.balance || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
      loadUsers(state.usersPage);
    } catch (err) {
      toast(err.message || "调整余额失败", true);
      button.disabled = false;
    }
  }

  async function setUserMode(userId, isSimulated, select) {
    select.disabled = true;
    try {
      const data = await api("/api/admin/users/" + userId + "/simulated", {
        method: "POST",
        body: JSON.stringify({ is_simulated: isSimulated }),
      });
      toast("账号类型已切换为" + (data.mode_name || (isSimulated ? "模拟交易账号" : "真实交易账号")));
    } catch (err) {
      toast(err.message || "切换账号类型失败", true);
      loadUsers(state.usersPage);
    } finally {
      select.disabled = false;
    }
  }

  async function deleteUser(userId, username) {
    if (!window.confirm("确定删除用户「" + username + "」？该操作不可恢复。")) return;
    try {
      await api("/api/admin/users/" + userId, { method: "DELETE" });
      toast("用户已删除");
      loadUsers(state.usersPage);
    } catch (err) {
      toast(err.message || "删除失败", true);
    }
  }

  document.getElementById("userSearchBtn").addEventListener("click", function () {
    state.usersQuery = document.getElementById("userSearch").value.trim();
    state.usersPage = 1;
    loadUsers(1);
  });

  document.getElementById("userSearch").addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      document.getElementById("userSearchBtn").click();
    }
  });

  document.getElementById("createUserForm").addEventListener("submit", async function (event) {
    event.preventDefault();
    const usernameInput = document.getElementById("newUsername");
    const passwordInput = document.getElementById("newPassword");
    const modeInput = document.getElementById("newUserMode");
    const button = document.getElementById("createUserBtn");
    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    if (!username || !password) {
      toast("请填写新用户名和初始密码", true);
      return;
    }
    button.disabled = true;
    try {
      await api("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({
          username: username,
          password: password,
          is_simulated: Number(modeInput.value),
        }),
      });
      usernameInput.value = "";
      passwordInput.value = "";
      modeInput.value = "1";
      toast("用户已创建");
      loadUsers(1);
      state.loaded.overview = false;
    } catch (err) {
      toast(err.message || "创建失败", true);
    } finally {
      button.disabled = false;
    }
  });

  /* ---------- Logins ---------- */

  async function loadLogins(page) {
    state.loginsPage = page;
    const tbody = document.getElementById("loginsBody");
    try {
      const query = new URLSearchParams({
        page: String(page),
        page_size: "30",
      });
      if (state.onlyFailed) query.set("only_failed", "true");
      const data = await api("/api/admin/logins?" + query.toString());
      renderLogins(data.items || []);
      updatePager("logins", page, data.total, 30);
    } catch (err) {
      emptyRow(tbody, 5, err.message || "读取失败");
      if (err.status !== 401) toast(err.message || "读取日志失败", true);
    }
  }

  function renderLogins(rows) {
    const tbody = document.getElementById("loginsBody");
    if (!rows.length) {
      emptyRow(tbody, 5, "暂无登录记录");
      return;
    }
    tbody.replaceChildren();
    rows.forEach(function (row) {
      const tr = el("tr");
      tr.appendChild(el("td", "mono", formatTime(row.created_at)));
      tr.appendChild(el("td", null, row.username || "—"));
      tr.appendChild(el("td", "mono", row.ip || "—"));
      const resultCell = el("td");
      resultCell.appendChild(resultTag(!!row.success));
      tr.appendChild(resultCell);
      tr.appendChild(el("td", null, row.message || "—"));
      tbody.appendChild(tr);
    });
  }

  document.getElementById("onlyFailed").addEventListener("change", function (event) {
    state.onlyFailed = event.target.checked;
    loadLogins(1);
  });

  /* ---------- Screens ---------- */

  async function loadScreens(page) {
    state.screensPage = page;
    const tbody = document.getElementById("screensBody");
    try {
      const query = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      const data = await api("/api/admin/screens?" + query.toString());
      renderScreens(data.items || []);
      updatePager("screens", page, data.total, PAGE_SIZE);
    } catch (err) {
      emptyRow(tbody, 6, err.message || "读取失败");
      if (err.status !== 401) toast(err.message || "读取选股记录失败", true);
    }
  }

  function renderScreens(rows) {
    const tbody = document.getElementById("screensBody");
    if (!rows.length) {
      emptyRow(tbody, 6, "暂无选股记录");
      return;
    }
    tbody.replaceChildren();
    rows.forEach(function (row) {
      const tr = el("tr");
      tr.appendChild(el("td", "mono", formatTime(row.created_at)));
      tr.appendChild(el("td", null, row.username || "—"));
      tr.appendChild(
        el("td", "mono", "¥" + Number(row.capital || 0).toLocaleString("zh-CN"))
      );

      const candidates = Array.isArray(row.candidates) ? row.candidates : [];
      const candidatesCell = el("td", "mono", candidates.length ? candidates.join(", ") : "—");
      candidatesCell.title = candidates.join(", ");
      tr.appendChild(candidatesCell);

      const allocations = Array.isArray(row.allocations) ? row.allocations : [];
      const allocationText = allocations
        .map(function (item) {
          return item.symbol + " " + (item.shares || 0) + "股";
        })
        .join(" / ");
      const allocationCell = el("td", "mono", allocationText || "—");
      allocationCell.title = allocations
        .map(function (item) {
          return item.symbol + " " + (item.amount || 0) + "元";
        })
        .join(" / ");
      tr.appendChild(allocationCell);

      const summaryCell = el(
        "td",
        null,
        row.summary ? String(row.summary).slice(0, 60) + (String(row.summary).length > 60 ? "…" : "") : "—"
      );
      summaryCell.title = row.summary || "";
      summaryCell.style.whiteSpace = "normal";
      summaryCell.style.minWidth = "220px";
      tr.appendChild(summaryCell);
      tbody.appendChild(tr);
    });
  }

  /* ---------- Trades ---------- */

  async function loadTrades(page) {
    state.tradesPage = page;
    const tbody = document.getElementById("tradesBody");
    try {
      const query = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      const data = await api("/api/admin/trades?" + query.toString());
      renderTrades(data.items || []);
      updatePager("trades", page, data.total, PAGE_SIZE);
    } catch (err) {
      emptyRow(tbody, 8, err.message || "读取失败");
      if (err.status !== 401) toast(err.message || "读取交易记录失败", true);
    }
  }

  function money(value) {
    const number = Number(value || 0);
    const sign = number < 0 ? "-" : "";
    return (
      sign +
      "¥" +
      Math.abs(number).toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    );
  }

  function renderTrades(rows) {
    const tbody = document.getElementById("tradesBody");
    if (!rows.length) {
      emptyRow(tbody, 8, "暂无交易记录");
      return;
    }
    tbody.replaceChildren();
    rows.forEach(function (row) {
      const tr = el("tr");
      tr.appendChild(el("td", "mono", formatTime(row.created_at)));
      tr.appendChild(el("td", null, row.username || "—"));
      tr.appendChild(el("td", null, row.mode_name || row.mode || "—"));
      tr.appendChild(el("td", "mono", money(row.cost)));

      const pnl = Number(row.profit || 0);
      const valueCell = el("td", "mono", money(row.market_value));
      tr.appendChild(valueCell);
      const profitCell = el("td", "mono " + (pnl > 0 ? "is-up" : pnl < 0 ? "is-down" : ""), money(pnl));
      tr.appendChild(profitCell);
      tr.appendChild(el("td", null, row.status === "open" ? "持仓中" : row.status));

      const positions = Array.isArray(row.positions) ? row.positions : [];
      const detail = positions
        .map(function (item) {
          return (
            item.symbol +
            " " +
            item.shares +
            "股 @" +
            Number(item.buy_price || 0).toFixed(2)
          );
        })
        .join(" / ");
      const positionCell = el("td", "mono", detail || "—");
      positionCell.title = positions
        .map(function (item) {
          return (
            item.symbol +
            " " +
            item.name +
            " 成本 " +
            Number(item.cost || 0).toFixed(2) +
            " 市值 " +
            Number(item.market_value || 0).toFixed(2)
          );
        })
        .join("\n");
      tr.appendChild(positionCell);
      tbody.appendChild(tr);
    });
  }

  /* ---------- Pagination ---------- */

  function updatePager(kind, page, total, size) {
    const info = document.getElementById(kind + "PagerInfo");
    const prev = document.getElementById(kind + "Prev");
    const next = document.getElementById(kind + "Next");
    const pages = Math.max(1, Math.ceil(total / size));
    info.textContent = "第 " + page + " / " + pages + " 页 · 共 " + total + " 条";
    prev.disabled = page <= 1;
    next.disabled = page >= pages;
  }

  [["users", loadUsers], ["logins", loadLogins], ["screens", loadScreens], ["trades", loadTrades]].forEach(
    function (pair) {
      const kind = pair[0];
      const loader = pair[1];
      document.getElementById(kind + "Prev").addEventListener("click", function () {
        if (state[kind + "Page"] > 1) loader(state[kind + "Page"] - 1);
      });
      document.getElementById(kind + "Next").addEventListener("click", function () {
        loader(state[kind + "Page"] + 1);
      });
    }
  );

  document.getElementById("overviewRefresh").addEventListener("click", loadOverview);

  /* ---------- Boot ---------- */

  async function boot() {
    try {
      const data = await api("/api/admin/me");
      showApp(data.admin && data.admin.username);
    } catch (err) {
      showLoginView();
    }
  }

  boot();
})();
