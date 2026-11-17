(function () {
  "use strict";

  const form = document.getElementById("authForm");
  const usernameInput = document.getElementById("username");
  const passwordInput = document.getElementById("password");
  const submitBtn = document.getElementById("authSubmit");
  const errorBox = document.getElementById("authError");
  const passwordHint = document.getElementById("passwordHint");
  const tabs = Array.from(document.querySelectorAll(".auth-tab"));

  let mode = "login";
  let busy = false;

  function targetPath() {
    const next = new URLSearchParams(window.location.search).get("next") || "/";
    if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
      return "/";
    }
    if (next === "/login" || next.startsWith("/login?")) {
      return "/";
    }
    return next;
  }

  function showError(message) {
    errorBox.textContent = message || "";
    errorBox.classList.toggle("hidden", !message);
  }

  function setBusy(value) {
    busy = value;
    submitBtn.disabled = value;
    submitBtn.textContent = value ? "请稍候…" : mode === "login" ? "登录" : "注册并登录";
    usernameInput.disabled = value;
    passwordInput.disabled = value;
  }

  function setMode(next) {
    mode = next === "register" ? "register" : "login";
    tabs.forEach(function (tab) {
      const active = tab.dataset.mode === mode;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    passwordInput.autocomplete = mode === "login" ? "current-password" : "new-password";
    passwordHint.textContent = mode === "login" ? "登录后自动保持 7 天" : "注册密码长度 6-64 位";
    submitBtn.textContent = mode === "login" ? "登录" : "注册并登录";
    showError("");
  }

  async function request(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    let data = null;
    try {
      data = await response.json();
    } catch (err) {
      data = null;
    }
    if (!response.ok) {
      const detail = data && (data.detail || data.message);
      let message = "请求失败，请稍后重试";
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail) && detail.length) {
        message = detail[0].msg || message;
      }
      throw new Error(message);
    }
    return data || {};
  }

  async function redirectIfLoggedIn() {
    try {
      const response = await fetch("/api/auth/me", { credentials: "same-origin" });
      if (response.ok) {
        window.location.replace(targetPath());
        return true;
      }
    } catch (err) {
      /* ignore network errors and show the form */
    }
    return false;
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      if (busy) return;
      setMode(tab.dataset.mode);
    });
  });

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    if (busy) return;
    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    if (!username || !password) {
      showError("请输入用户名和密码");
      return;
    }
    if (mode === "register" && password.length < 6) {
      showError("密码至少 6 位");
      return;
    }
    showError("");
    setBusy(true);
    try {
      await request(mode === "login" ? "/api/auth/login" : "/api/auth/register", {
        username: username,
        password: password,
      });
      window.location.replace(targetPath());
    } catch (err) {
      showError(err && err.message ? err.message : "登录失败，请稍后重试");
      setBusy(false);
    }
  });

  setMode("login");
  redirectIfLoggedIn();
  usernameInput.focus();
})();
