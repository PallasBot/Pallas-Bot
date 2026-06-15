# ruff: noqa: E501
"""管理页 HTML 模板与内嵌 CSS。"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape as html_escape

from ..contract import resolve_public_mount_path


def shell_brand_mark_src(public_base_path: str) -> str:
    """侧栏品牌图。"""
    p = (public_base_path or "").strip().rstrip("/")
    return f"{p}/_pallas_ui/favicon.png" if p else "/_pallas_ui/favicon.png"


def shell_favicon_link(public_base_path: str) -> str:
    """favicon：静态目录 ``favicon.png``。"""
    href = shell_brand_mark_src(public_base_path)
    return f'  <link rel="icon" type="image/png" href="{html_escape(href, quote=True)}" />\n'


def shell_footer_html() -> str:
    y = datetime.now().year
    return f'    <footer class="shell-footer" role="contentinfo">© {y} Pallas-Bot</footer>\n'


def shell_font_stylesheet_link(public_base_path: str) -> str:
    """与 WebUI index.html 一致：Plus Jakarta Sans + Noto Sans SC + JetBrains Mono。"""
    gfont = (
        "https://fonts.googleapis.com/css2?"
        "family=JetBrains+Mono:wght@400;500"
        "&family=Noto+Sans+SC:wght@400;500;600;700"
        "&family=Plus+Jakarta+Sans:wght@400;500;600;700;800"
        "&display=swap"
    )
    return (
        '  <link rel="preconnect" href="https://fonts.googleapis.com" />\n'
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n'
        f'  <link rel="stylesheet" href="{html_escape(gfont, quote=True)}" />\n'
    )


def shell_stylesheet_link(public_base_path: str) -> str:
    """协议壳主样式。"""
    p = (public_base_path or "").strip().rstrip("/")
    href = f"{p}/_pallas_ui/shell.css" if p else "/_pallas_ui/shell.css"
    return f'  <link rel="stylesheet" href="{html_escape(href, quote=True)}" />\n'


def shell_head_assets(public_base_path: str) -> str:
    return (
        shell_favicon_link(public_base_path)
        + shell_font_stylesheet_link(public_base_path)
        + shell_stylesheet_link(public_base_path)
    )


def _normalize_pallas_console_http_base(raw: str | None) -> str:
    s = (raw or "").strip() or "/pallas"
    if not s.startswith("/"):
        s = "/" + s
    s = s.rstrip("/")
    return s or "/pallas"


def shell_pallas_web_console_topbar_chunk(pallas_console_http_base: str) -> str:
    root_js = json.dumps(_normalize_pallas_console_http_base(pallas_console_http_base))
    return (
        '<a class="btn secondary" id="linkPallasWebConsole" href="#" target="_blank" rel="noopener noreferrer">'
        "前往前端控制台</a>"
        f"<script>(function(){{var e=document.getElementById('linkPallasWebConsole');"
        f"if(e)e.href=location.origin+{root_js}+'/';}})();</script>"
    )


def shell_pallas_web_console_nav_link(
    pallas_console_http_base: str,
    *,
    link_class: str = "shell__nav-link",
    element_id: str = "linkPallasWebConsole",
) -> str:
    """侧栏 / 移动抽屉「前端控制台」入口。"""
    root_js = json.dumps(_normalize_pallas_console_http_base(pallas_console_http_base))
    eid = html_escape(element_id, quote=True)
    return (
        f'<a class="{html_escape(link_class)} shell__nav-link--ext" id="{eid}" href="#" title="前端控制台" '
        'target="_blank" rel="noopener noreferrer">'
        '<span class="shell__nav-ico" aria-hidden="true">↗</span>'
        '<span class="shell__nav-text"><span class="shell__nav-label">前端控制台</span>'
        '<span class="shell__nav-desc">Pallas WebUI</span></span></a>'
        f"<script>(function(){{var e=document.getElementById({json.dumps(element_id)});"
        f"if(e)e.href=location.origin+{root_js}+'/';}})();</script>"
    )


_PROTOCOL_NAV: tuple[tuple[str, str, str, str, str], ...] = (
    ("dashboard", "", "📊", "仪表盘", "账号与运行日志"),
    ("new", "/new", "➕", "创建账号", "新建协议实例"),
    ("import", "/import", "📥", "导入账号", "批量导入旧数据"),
    ("assets", "/assets", "📦", "协议资产", "运行时与镜像"),
    ("settings", "/settings", "⚙", "偏好设置", "外观与轮询"),
)


def _render_protocol_nav_links(
    base_path: str,
    active: str,
    *,
    link_class: str,
) -> str:
    p = (base_path or "").strip().rstrip("/")
    links: list[str] = []
    for nav_id, suffix, icon, label, desc in _PROTOCOL_NAV:
        href = html_escape(f"{p}{suffix}" if suffix else f"{p}/", quote=True)
        cls = f"{link_class} is-router-active" if nav_id == active else link_class
        label_esc = html_escape(label)
        links.append(
            f'<a class="{cls}" href="{href}" title="{label_esc}">'
            f'<span class="shell__nav-ico" aria-hidden="true">{html_escape(icon)}</span>'
            f'<span class="shell__nav-text"><span class="shell__nav-label">{label_esc}</span>'
            f'<span class="shell__nav-desc">{html_escape(desc)}</span></span></a>'
        )
    return "\n        ".join(links)


def _render_protocol_sidebar(base_path: str, active: str, pallas_console_http_base: str) -> str:
    p = (base_path or "").strip().rstrip("/")
    home = html_escape(f"{p}/", quote=True)
    nav_body = _render_protocol_nav_links(base_path, active, link_class="shell__nav-link")
    ext = shell_pallas_web_console_nav_link(pallas_console_http_base)
    mark_src = html_escape(shell_brand_mark_src(p), quote=True)
    return f"""    <aside class="shell__sidebar" aria-label="协议端导航">
      <div class="shell__sidebar-top">
        <a class="shell__brand" href="{home}">
          <img class="shell__brand-mark" src="{mark_src}" alt="" width="28" height="28" decoding="async" />
          <span class="shell__brand-text">
            <span class="shell__brand-name shell__title">Pallas-Bot</span>
            <span class="shell__brand-sub">协议端</span>
          </span>
        </a>
      </div>
      <nav class="shell__nav">
        <div class="shell__nav-section">管理</div>
        {nav_body}
        <div class="shell__nav-section">外部</div>
        {ext}
      </nav>
    </aside>"""


def _render_protocol_mobile_nav(base_path: str, active: str, pallas_console_http_base: str) -> str:
    mark_src = html_escape(shell_brand_mark_src(base_path), quote=True)
    nav_body = _render_protocol_nav_links(base_path, active, link_class="shell-mobile-nav__link")
    ext = shell_pallas_web_console_nav_link(
        pallas_console_http_base,
        link_class="shell-mobile-nav__link",
        element_id="linkPallasWebConsoleMobile",
    )
    return f"""  <div id="protoMobileNav" class="shell-mobile-nav" hidden>
    <aside id="proto-mobile-nav-panel" class="shell-mobile-nav__panel" role="dialog" aria-modal="true" aria-label="协议端导航">
      <div class="shell-mobile-nav__head">
        <div class="shell-mobile-nav__brand-block">
          <img class="shell-mobile-nav__mark" src="{mark_src}" alt="" width="28" height="28" decoding="async" />
          <div class="shell-mobile-nav__brand-text">
            <span class="shell-mobile-nav__brand">Pallas-Bot</span>
            <span class="shell-mobile-nav__ver">协议端</span>
          </div>
        </div>
        <button type="button" class="shell-mobile-nav__close" id="protoMobileNavClose" aria-label="关闭菜单">×</button>
      </div>
      <nav class="shell-mobile-nav__links" aria-label="协议端导航">
        <div class="shell-mobile-nav__section" role="presentation">管理</div>
        {nav_body}
        <div class="shell-mobile-nav__section" role="presentation">外部</div>
        {ext}
      </nav>
    </aside>
    <div class="shell-mobile-nav__backdrop" id="protoMobileNavBackdrop" aria-hidden="true"></div>
  </div>"""


def shell_topbar_collapse_html() -> str:
    return """      <div class="shell__topbar-start">
        <div class="shell__topbar-rail">
          <button type="button" class="shell__topbar-collapse" id="protoSidebarCollapse" aria-expanded="true" aria-label="收起菜单栏">«</button>
          <button type="button" class="shell__topbar-menu" id="protoMobileNavOpen" aria-label="打开导航菜单" aria-controls="proto-mobile-nav-panel">☰</button>
          <span class="shell__topbar-vrule" aria-hidden="true"></span>
        </div>
      </div>"""


def shell_topbar_theme_html() -> str:
    moon = (
        '<svg class="shell__ico" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
    )
    sun = (
        '<svg class="shell__ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.41 1.41m11.31 11.31l1.41 1.41'
        'M19.07 4.93l-1.41 1.41M6.34 17.66l-1.41 1.41"/></svg>'
    )
    monitor = (
        '<svg class="shell__ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>'
    )
    return f"""        <div class="shell-toolbar__seg shell-toolbar__seg--compact shell__topbar-theme" role="group" aria-label="颜色模式">
          <button type="button" data-proto-theme="dark" title="深色" aria-label="深色">
            <span class="shell__theme-ico">{moon}</span>
          </button>
          <button type="button" data-proto-theme="light" title="浅色" aria-label="浅色">
            <span class="shell__theme-ico">{sun}</span>
          </button>
          <button type="button" data-proto-theme="system" title="跟随系统" aria-label="跟随系统">
            <span class="shell__theme-ico">{monitor}</span>
          </button>
        </div>"""


def render_protocol_shell_open(
    base_path: str,
    pallas_console_http_base: str,
    *,
    active: str,
    page_title: str,
    page_desc: str = "",
    topbar_actions: str = "",
) -> str:
    sidebar = _render_protocol_sidebar(base_path, active, pallas_console_http_base)
    title_esc = html_escape(page_title)
    desc_block = (
        f'<p class="shell__topbar-desc muted shell__topbar-desc--hide-narrow">{html_escape(page_desc)}</p>'
        if (page_desc or "").strip()
        else ""
    )
    return f"""  <div class="shell__bg" aria-hidden="true"></div>
  <div class="shell proto-shell">
{sidebar}
    <header class="shell__topbar">
{shell_topbar_collapse_html()}
      <div class="shell__topbar-lead">
        <h1 class="shell__topbar-title"><span class="shell__topbar-title-text">{title_esc}</span></h1>
        {desc_block}
      </div>
      <div class="shell__topbar-end row-actions">
{shell_topbar_theme_html()}
        {topbar_actions}
        <button class="btn secondary shell__topbar-exit" type="button" data-action="logout" title="退出登录" aria-label="退出登录">退出</button>
      </div>
    </header>
    <main class="shell__main">
      <div class="shell__main-inner proto-shell__main-inner">
"""


def render_protocol_shell_close(
    base_path: str,
    *,
    active: str,
    pallas_console_http_base: str,
) -> str:
    mobile_nav = _render_protocol_mobile_nav(base_path, active, pallas_console_http_base)
    return f"""{shell_footer_html()} </div>
    </main>
  </div>
{mobile_nav}
"""


def _pallas_theme_bridge_js() -> str:
    """与 Pallas-Bot-WebUI consolePrefs 共用 pallas_console_prefs_v1。"""
    return """
    const PALLAS_CONSOLE_PREFS_KEY = "pallas_console_prefs_v1";
    const PALLAS_THEME_KEY = "pallas-webui-theme";
    const PALLAS_PROTOCOL_THEME_LEGACY = "pallas_protocol_theme";
    const PALLAS_THEME_MODE_KEY = "pallas-theme-mode";
    const __SHELL_ACCENT_IDS = ["sky", "indigo", "emerald", "rose", "amber", "violet"];
    function readConsolePrefsJson() {
      try {
        const raw = localStorage.getItem(PALLAS_CONSOLE_PREFS_KEY);
        if (!raw) return {};
        const o = JSON.parse(raw);
        return o && typeof o === "object" ? o : {};
      } catch (e) { return {}; }
    }
    function writeConsolePrefsJson(patch) {
      try {
        const cur = readConsolePrefsJson();
        localStorage.setItem(PALLAS_CONSOLE_PREFS_KEY, JSON.stringify({ ...cur, ...patch }));
      } catch (e) {}
    }
    function resolveThemeModeFromStorage() {
      const prefs = readConsolePrefsJson();
      let mode = prefs.theme;
      if (mode !== "dark" && mode !== "light" && mode !== "system") {
        try {
          const legacy = localStorage.getItem(PALLAS_THEME_MODE_KEY);
          if (legacy === "dark" || legacy === "light" || legacy === "system") mode = legacy;
        } catch (e) {}
      }
      if (mode !== "dark" && mode !== "light" && mode !== "system") return "system";
      return mode;
    }
    function resolvePallasThemePreference() {
      const mode = resolveThemeModeFromStorage();
      if (mode === "system") {
        try {
          return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
        } catch (e) { return "light"; }
      }
      return mode;
    }
    function applyPallasShellTheme(resolved, options) {
      const next = resolved === "dark" ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      document.documentElement.style.colorScheme = next;
      document.body.setAttribute("data-theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
      const persist = options && options.persist;
      if (!persist) return;
      try {
        localStorage.setItem(PALLAS_THEME_KEY, next);
        localStorage.setItem(PALLAS_PROTOCOL_THEME_LEGACY, next);
      } catch (e) {}
    }
    function initPallasShellThemeFromStorage() {
      applyPallasShellTheme(resolvePallasThemePreference(), { persist: false });
    }
    try {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        if (resolveThemeModeFromStorage() === "system") {
          applyPallasShellTheme(resolvePallasThemePreference(), { persist: false });
        }
      });
    } catch (e) {}
"""


def _shell_prefs_js() -> str:
    """与 WebUI consolePrefs：data-accent / data-radius / data-density。"""
    return """
    function applyShellUiPrefsFromStorage() {
      const prefs = readConsolePrefsJson();
      const root = document.documentElement;
      const accent = __SHELL_ACCENT_IDS.includes(prefs.accentPreset) ? prefs.accentPreset : "sky";
      root.dataset.accent = accent;
      const radius = prefs.radius === "tight" || prefs.radius === "round" ? prefs.radius : "default";
      if (radius === "default") delete root.dataset.radius;
      else root.dataset.radius = radius;
      const density = prefs.density === "compact" ? "compact" : "comfortable";
      if (density === "comfortable") delete root.dataset.density;
      else root.dataset.density = density;
    }
    try {
      window.addEventListener("storage", (e) => {
        if (!e || !e.key) return;
        if (e.key === PALLAS_CONSOLE_PREFS_KEY || e.key === PALLAS_THEME_MODE_KEY || e.key === PALLAS_THEME_KEY) {
          applyShellUiPrefsFromStorage();
          applySidebarCollapsedFromStorage();
          syncShellThemeToolbar();
          if (e.key === PALLAS_CONSOLE_PREFS_KEY || e.key === PALLAS_THEME_MODE_KEY || e.key === PALLAS_THEME_KEY) {
            applyPallasShellTheme(resolvePallasThemePreference(), { persist: false });
          }
        }
      });
    } catch (e) {}
    try {
      applyShellUiPrefsFromStorage();
    } catch (e) {}
"""


def _shell_chrome_js() -> str:
    return """
    const PROTO_SHELL_NARROW_MQ = "(max-width: 860px)";
    function isProtoShellNarrow() {
      try { return window.matchMedia(PROTO_SHELL_NARROW_MQ).matches; } catch (e) { return false; }
    }
    function openProtocolMobileNav() {
      const root = document.getElementById("protoMobileNav");
      if (!root) return;
      root.hidden = false;
      document.body.classList.add("shell-mobile-nav-open");
    }
    function closeProtocolMobileNav() {
      const root = document.getElementById("protoMobileNav");
      if (!root) return;
      root.hidden = true;
      document.body.classList.remove("shell-mobile-nav-open");
    }
    function syncShellThemeToolbar() {
      const mode = resolveThemeModeFromStorage();
      document.querySelectorAll("[data-proto-theme]").forEach((btn) => {
        const m = btn.getAttribute("data-proto-theme");
        btn.classList.toggle("is-on", m === mode);
      });
    }
    function applySidebarCollapsedFromStorage() {
      const collapsed = !!readConsolePrefsJson().sidebarCollapsed;
      document.querySelectorAll(".proto-shell").forEach((el) => {
        el.classList.toggle("shell--sidebar-collapsed", collapsed);
      });
      const btn = document.getElementById("protoSidebarCollapse");
      if (!btn) return;
      btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      btn.textContent = collapsed ? "»" : "«";
      btn.setAttribute("aria-label", collapsed ? "展开菜单栏" : "收起菜单栏");
    }
    function toggleProtocolSidebar() {
      const prefs = readConsolePrefsJson();
      writeConsolePrefsJson({ sidebarCollapsed: !prefs.sidebarCollapsed });
      applySidebarCollapsedFromStorage();
    }
    function setConsoleThemeMode(mode) {
      if (mode !== "dark" && mode !== "light" && mode !== "system") return;
      writeConsolePrefsJson({ theme: mode });
      applyPallasShellTheme(resolvePallasThemePreference(), { persist: false });
      syncShellThemeToolbar();
    }
    function initProtocolShellChrome() {
      applySidebarCollapsedFromStorage();
      syncShellThemeToolbar();
      const collapseBtn = document.getElementById("protoSidebarCollapse");
      if (collapseBtn && !collapseBtn.dataset.bound) {
        collapseBtn.dataset.bound = "1";
        collapseBtn.addEventListener("click", toggleProtocolSidebar);
      }
      const mobileOpenBtn = document.getElementById("protoMobileNavOpen");
      if (mobileOpenBtn && !mobileOpenBtn.dataset.bound) {
        mobileOpenBtn.dataset.bound = "1";
        mobileOpenBtn.addEventListener("click", openProtocolMobileNav);
      }
      const mobileCloseBtn = document.getElementById("protoMobileNavClose");
      if (mobileCloseBtn && !mobileCloseBtn.dataset.bound) {
        mobileCloseBtn.dataset.bound = "1";
        mobileCloseBtn.addEventListener("click", closeProtocolMobileNav);
      }
      const mobileBackdrop = document.getElementById("protoMobileNavBackdrop");
      if (mobileBackdrop && !mobileBackdrop.dataset.bound) {
        mobileBackdrop.dataset.bound = "1";
        mobileBackdrop.addEventListener("click", closeProtocolMobileNav);
      }
      document.querySelectorAll("#protoMobileNav .shell-mobile-nav__link").forEach((link) => {
        if (link.dataset.bound) return;
        link.dataset.bound = "1";
        link.addEventListener("click", () => {
          if (isProtoShellNarrow()) closeProtocolMobileNav();
        });
      });
      if (!window.__protoShellNarrowMqBound) {
        window.__protoShellNarrowMqBound = true;
        try {
          window.matchMedia(PROTO_SHELL_NARROW_MQ).addEventListener("change", () => {
            if (!isProtoShellNarrow()) closeProtocolMobileNav();
          });
        } catch (e) {}
      }
      document.querySelectorAll("[data-proto-theme]").forEach((btn) => {
        if (btn.dataset.bound) return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => {
          setConsoleThemeMode(btn.getAttribute("data-proto-theme"));
        });
      });
    }
    try {
      document.addEventListener("DOMContentLoaded", () => {
        try { initProtocolShellChrome(); } catch (e) {}
      });
    } catch (e) {}
"""


def _render_common_api_js() -> str:
    return (
        _pallas_theme_bridge_js()
        + _shell_prefs_js()
        + _shell_chrome_js()
        + """
    function getSessionToken() {
      return (sessionStorage.getItem("pallas_protocol_token_session") || "").trim();
    }

    async function logout() {
      sessionStorage.removeItem("pallas_protocol_token_session");
      try {
        await fetch(`${basePath}/logout`, { method: "POST" });
      } finally {
        location.href = `${basePath}/login`;
      }
    }

    async function api(path, options = {}) {
      const timeoutMs = typeof options.timeoutMs === "number" ? options.timeoutMs : 35000;
      const fetchOpts = { ...options };
      delete fetchOpts.timeoutMs;
      const token = getSessionToken();
      const headers = fetchOpts.headers || {};
      if (token) headers["X-Pallas-Protocol-Token"] = token;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        const res = await fetch(`${basePath}${path}`, {
          ...fetchOpts,
          headers,
          signal: ctrl.signal,
          credentials: fetchOpts.credentials || "same-origin",
        });
        if (res.status === 401) {
          sessionStorage.removeItem("pallas_protocol_token_session");
          const loc = location.pathname + location.search + location.hash;
          const next = encodeURIComponent(loc || `${basePath}/`);
          location.href = `${basePath}/login?next=${next}&reason=${encodeURIComponent("登录已失效或 Token 无效，请重新登录")}`;
          throw new Error("Unauthorized");
        }
        if (!res.ok) throw new Error((await res.text()) || res.status);
        return res.json();
      } catch (e) {
        if (e && e.name === "AbortError") throw new Error("请求超时，请稍后重试");
        throw e;
      } finally {
        clearTimeout(timer);
      }
    }

    document.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-action='logout']");
      if (!btn) return;
      e.preventDefault();
      logout();
    });

    function isLogElementUserSelecting(el) {
      if (!el) return false;
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) return false;
      if (sel.isCollapsed) return false;
      try {
        const r = sel.getRangeAt(0);
        return el.contains(r.commonAncestorContainer);
      } catch (e) {
        return false;
      }
    }

    function shouldPauseLiveLogDomWrite(el) {
      if (!el) return false;
      if (isLogElementUserSelecting(el)) return true;
      if (el.id === "accLogs") return false;
      try {
        if (typeof el.matches === "function" && el.matches(":focus-within")) return true;
      } catch (e) { }
      return false;
    }

    let protoMainScrollActive = false;
    let protoMainScrollTimer = null;
    const protoScrollEndHooks = [];
    function isProtoMainInnerScrolling() {
      return protoMainScrollActive;
    }
    function onProtoMainInnerScrollEnd(fn) {
      if (typeof fn === "function") protoScrollEndHooks.push(fn);
    }
    function wireProtoMainInnerScrollPause() {
      const el = document.querySelector(".proto-shell__main-inner");
      if (!el || el.dataset.protoScrollBound) return;
      el.dataset.protoScrollBound = "1";
      el.addEventListener("scroll", () => {
        protoMainScrollActive = true;
        clearTimeout(protoMainScrollTimer);
        protoMainScrollTimer = setTimeout(() => {
          protoMainScrollActive = false;
          protoScrollEndHooks.forEach((hook) => {
            try { hook(); } catch (e) {}
          });
        }, 400);
      }, { passive: true });
    }
    try {
      document.addEventListener("DOMContentLoaded", wireProtoMainInnerScrollPause);
    } catch (e) {}
    try { wireProtoMainInnerScrollPause(); } catch (e) {}

    function copyPlainStrToast(msg, level) {
      if (typeof notify === "function") notify(msg, level);
      else alert(msg);
    }

    function copyPlainStr(t) {
      const x = String(t ?? "");
      if (!x) {
        copyPlainStrToast("无可复制内容", "warn");
        return;
      }
      const ok = () => copyPlainStrToast("已复制", "ok");
      const fail = (e) => copyPlainStrToast(String(e && e.message ? e.message : e), "err");
      const runFallback = () => {
        try {
          const ta = document.createElement("textarea");
          ta.value = x;
          ta.style.position = "fixed";
          ta.style.left = "-9999px";
          ta.setAttribute("readonly", "");
          document.body.appendChild(ta);
          ta.select();
          ta.setSelectionRange(0, x.length);
          const done = document.execCommand("copy");
          document.body.removeChild(ta);
          if (done) ok();
          else fail(new Error("浏览器拒绝了复制"));
        } catch (err) {
          fail(err);
        }
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(x).then(ok).catch(() => runFallback());
      } else {
        runFallback();
      }
    }

    document.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-copy-plain]");
      if (!btn) return;
      e.preventDefault();
      const raw = btn.getAttribute("data-copy-plain");
      copyPlainStr(raw != null ? decodeURIComponent(raw) : "");
    });

    function shellPrettySyncSelect(sel) {
      const wrap = sel && sel.closest ? sel.closest(".shell-pretty-wrap") : null;
      if (wrap && typeof wrap._shellPrettyRebuild === "function") wrap._shellPrettyRebuild();
    }

    function wireShellPrettySelect(sel) {
      if (!sel || sel.multiple || sel.dataset.shellPrettyWired) return;
      sel.dataset.shellPrettyWired = "1";
      sel.classList.remove("shell-pretty-select");
      const wrap = document.createElement("div");
      wrap.className = "shell-pretty-wrap";
      sel.parentNode.insertBefore(wrap, sel);
      wrap.appendChild(sel);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "shell-pretty-btn";
      btn.setAttribute("aria-haspopup", "listbox");
      const panel = document.createElement("div");
      panel.className = "shell-pretty-panel";
      panel.setAttribute("role", "listbox");
      wrap.insertBefore(btn, sel);
      wrap.insertBefore(panel, sel);
      sel.classList.add("shell-pretty-native");
      function syncDisabled() {
        btn.disabled = !!sel.disabled;
      }
      function rebuild() {
        panel.innerHTML = "";
        Array.from(sel.options).forEach((opt, idx) => {
          const row = document.createElement("button");
          row.type = "button";
          row.className = "shell-pretty-option" + (idx === sel.selectedIndex ? " is-active" : "");
          row.textContent = opt.textContent;
          row.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            sel.selectedIndex = idx;
            sel.dispatchEvent(new Event("change", { bubbles: true }));
            panel.classList.remove("is-open");
            wrap.classList.remove("shell-pretty-wrap--open");
            syncBtn();
            rebuild();
          });
          panel.appendChild(row);
        });
      }
      function syncBtn() {
        const opt = sel.options[sel.selectedIndex];
        btn.textContent = opt ? opt.textContent : "";
      }
      wrap._shellPrettyRebuild = function () {
        syncBtn();
        rebuild();
        syncDisabled();
      };
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (sel.disabled) return;
        const willOpen = !panel.classList.contains("is-open");
        document.querySelectorAll(".shell-pretty-panel.is-open").forEach((p) => {
          p.classList.remove("is-open");
          const ow = p.closest(".shell-pretty-wrap");
          if (ow) ow.classList.remove("shell-pretty-wrap--open");
        });
        if (willOpen) {
          panel.classList.add("is-open");
          wrap.classList.add("shell-pretty-wrap--open");
        }
      });
      sel.addEventListener("change", () => {
        syncBtn();
        rebuild();
      });
      new MutationObserver(() => {
        syncBtn();
        rebuild();
      }).observe(sel, { childList: true });
      new MutationObserver(syncDisabled).observe(sel, { attributes: true, attributeFilter: ["disabled"] });
      syncBtn();
      rebuild();
      syncDisabled();
    }

    function initShellPrettySelects(root) {
      const scope = root || document;
      scope.querySelectorAll("select.shell-pretty-select").forEach(wireShellPrettySelect);
    }

    document.addEventListener("click", (e) => {
      if (e.target.closest && e.target.closest(".shell-pretty-wrap")) return;
      document.querySelectorAll(".shell-pretty-panel.is-open").forEach((p) => {
        p.classList.remove("is-open");
        const w = p.closest(".shell-pretty-wrap");
        if (w) w.classList.remove("shell-pretty-wrap--open");
      });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        document.querySelectorAll(".shell-pretty-panel.is-open").forEach((p) => {
          p.classList.remove("is-open");
          const w = p.closest(".shell-pretty-wrap");
          if (w) w.classList.remove("shell-pretty-wrap--open");
        });
      }
    });
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => initShellPrettySelects());
    } else {
      initShellPrettySelects();
    }
"""
    )


def _render_hidden_token_sync_js(back_button_id: str = "backDash", *, page_session: str = "") -> str:
    back_id_js = json.dumps(back_button_id)
    page_sess_js = json.dumps(page_session)
    return f"""
    (function initTokenSync() {{
      const u = new URL(location.href);
      const fromQs = (u.searchParams.get("token") || "").trim();
      const fromBootstrap = ({page_sess_js} || "").trim();
      const fromSession = (sessionStorage.getItem("pallas_protocol_token_session") || "").trim();
      const t = fromQs || fromBootstrap || fromSession;
      if (t) sessionStorage.setItem("pallas_protocol_token_session", t);
      const tokenEl = document.getElementById("token");
      if (tokenEl) tokenEl.value = t;
      const b = document.getElementById({back_id_js});
      if (b) b.href = basePath;
    }})();
"""


def render_settings_page(base_path: str, pallas_console_http_base: str = "/pallas") -> str:
    """协议端偏好设置：与 WebUI 共用 localStorage。"""
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    common_api_js = _render_common_api_js()
    token_sync_js = _render_hidden_token_sync_js("backDash")
    shell_open = render_protocol_shell_open(
        path,
        pallas_console_http_base,
        active="settings",
        page_title="偏好设置",
        page_desc="外观、轮询与控制台口令",
    )
    shell_close = render_protocol_shell_close(
        path, active="settings", pallas_console_http_base=pallas_console_http_base
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
{shell_head_assets(path)}  <title>偏好设置 · 协议端</title>
  <style>
.pref-card {{ margin-bottom: 14px; }}
.pref-title {{ margin: 0 0 6px; font-size: 1rem; }}
.pref-desc {{ margin: 0 0 12px; font-size: 0.82rem; color: var(--muted); line-height: 1.45; }}
.pref-row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
.pref-chip {{
  display: inline-flex; align-items: center; gap: 6px;
  border-radius: 10px; border: 1px solid var(--bd); padding: 9px 14px;
  font-size: 0.82rem; font-weight: 600; cursor: pointer;
  background: color-mix(in srgb, var(--bg1) 88%, transparent); color: var(--txt);
}}
.pref-chip.on {{ border-color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--accent-strong); }}
.pref-swatch {{
  width: 36px; height: 36px; border-radius: 50%; border: 2px solid var(--bd); cursor: pointer; padding: 0;
}}
.pref-swatch.on {{ border-color: var(--txt); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 35%, transparent); }}
.pref-dens {{
  display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}}
.pref-dens button {{
  text-align: left; border-radius: 12px; border: 1px solid var(--bd); padding: 14px 16px;
  cursor: pointer; background: var(--card); color: var(--txt); font: inherit;
}}
.pref-dens button.on {{ border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }}
.pref-dens .t {{ font-weight: 650; font-size: 0.88rem; display: block; margin-bottom: 4px; }}
.pref-dens .d {{ font-size: 0.72rem; color: var(--muted); line-height: 1.4; }}
  </style>
</head>
<body>
  <input type="hidden" id="token" value="" autocomplete="off" />
  {shell_open}
    <div class="section" style="max-width:52rem;margin:0 auto;padding-bottom:48px">
      <div class="card pref-card">
        <h3 class="pref-title">统一控制台口令</h3>
        <p class="pref-desc">保存后需重新登录。</p>
        <div class="pref-row" style="flex-direction:column;align-items:stretch;gap:10px">
          <input id="prefNewConsolePw" type="password" autocomplete="new-password" placeholder="新口令" style="width:100%;border-radius:10px;border:1px solid var(--bd);padding:10px 12px;font:inherit;background:var(--card);color:var(--txt)" />
          <input id="prefNewConsolePw2" type="password" autocomplete="new-password" placeholder="再次输入" style="width:100%;border-radius:10px;border:1px solid var(--bd);padding:10px 12px;font:inherit;background:var(--card);color:var(--txt)" />
          <button type="button" class="btn" id="prefBtnSaveConsolePw">保存新口令</button>
          <p class="muted" id="prefConsolePwMsg" style="margin:0;font-size:0.78rem"></p>
        </div>
      </div>
      <div class="card pref-card">
        <h3 class="pref-title">显示模式</h3>
        <p class="pref-desc">浅色 / 深色 / 跟随系统；与 Pallas-Bot 控制台、顶部栏切换共用存储键。</p>
        <div class="pref-row" id="prefThemeRow"></div>
      </div>
      <div class="card pref-card">
        <h3 class="pref-title">强调色</h3>
        <p class="pref-desc">与 Pallas-Bot 控制台偏好中的强调色预设共用存储。</p>
        <div class="pref-row" id="prefAccentRow"></div>
        <p class="muted" style="margin:10px 0 0;font-size:0.78rem" id="prefAccentHint"></p>
      </div>
      <div class="card pref-card">
        <h3 class="pref-title">圆角</h3>
        <div class="pref-row" id="prefRadiusRow"></div>
      </div>
      <div class="card pref-card">
        <h3 class="pref-title">显示密度</h3>
        <div class="pref-dens" id="prefDensityRow"></div>
      </div>
      <div class="card pref-card">
        <h3 class="pref-title">仪表盘轮询</h3>
        <p class="pref-desc">协议仪表盘「自动刷新日志」等定时拉取间隔（毫秒）；暂停即不后台拉取。</p>
        <div class="pref-row" id="prefPollRow"></div>
        <p class="muted" style="margin:10px 0 0;font-size:0.78rem" id="prefPollHint"></p>
      </div>
    </div>
{shell_close}
  <script>
    const basePath = {p};
{common_api_js}
{token_sync_js}
    initPallasShellThemeFromStorage();
    applyShellUiPrefsFromStorage();
    initProtocolShellChrome();
    const ACCENTS = [
      {{ id: "sky", label: "天蓝", swatch: "#38bdf8" }},
      {{ id: "indigo", label: "靛蓝", swatch: "#818cf8" }},
      {{ id: "emerald", label: "翠绿", swatch: "#34d399" }},
      {{ id: "rose", label: "玫红", swatch: "#fb7185" }},
      {{ id: "amber", label: "琥珀", swatch: "#fbbf24" }},
      {{ id: "violet", label: "紫罗兰", swatch: "#a78bfa" }},
    ];
    const RADII = [
      {{ id: "tight", label: "紧凑" }},
      {{ id: "default", label: "默认" }},
      {{ id: "round", label: "圆润" }},
    ];
    const POLLS = [
      {{ value: 0, label: "暂停" }},
      {{ value: 1500, label: "1.5 秒" }},
      {{ value: 3000, label: "3 秒" }},
      {{ value: 5000, label: "5 秒" }},
      {{ value: 10000, label: "10 秒" }},
      {{ value: 30000, label: "30 秒" }},
    ];
    function syncPrefsUi() {{
      const prefs = readConsolePrefsJson();
      try {{
        const mode = resolveThemeModeFromStorage();
        document.querySelectorAll("#prefThemeRow .pref-chip").forEach((b) => {{
          b.classList.toggle("on", b.dataset.mode === mode);
        }});
      }} catch (e) {{}}
      try {{
        const accent = __SHELL_ACCENT_IDS.includes(prefs.accentPreset) ? prefs.accentPreset : "sky";
        document.querySelectorAll("#prefAccentRow .pref-swatch").forEach((b) => {{
          b.classList.toggle("on", b.dataset.accent === accent);
        }});
        const lab = ACCENTS.find((a) => a.id === accent);
        document.getElementById("prefAccentHint").textContent = "当前：" + (lab ? lab.label : accent);
      }} catch (e) {{}}
      try {{
        const radius = prefs.radius === "tight" || prefs.radius === "round" ? prefs.radius : "default";
        document.querySelectorAll("#prefRadiusRow .pref-chip").forEach((b) => {{
          b.classList.toggle("on", b.dataset.radius === radius);
        }});
      }} catch (e) {{}}
      try {{
        const d = prefs.density === "compact" ? "compact" : "comfortable";
        document.querySelectorAll("#prefDensityRow button").forEach((b) => {{
          b.classList.toggle("on", b.dataset.density === d);
        }});
      }} catch (e) {{}}
      try {{
        const poll = parseInt(localStorage.getItem("pallas-dashboard-poll-ms") || "3000", 10);
        const pv = Number.isFinite(poll) ? poll : 3000;
        document.querySelectorAll("#prefPollRow .pref-chip").forEach((b) => {{
          b.classList.toggle("on", parseInt(b.dataset.ms || "0", 10) === pv);
        }});
        const hint = document.getElementById("prefPollHint");
        if (hint) hint.textContent = pv === 0 ? "当前：已暂停轮询" : ("当前：" + pv + " 毫秒");
      }} catch (e) {{}}
    }}
    function wirePrefsPage() {{
      const tr = document.getElementById("prefThemeRow");
      [["light","浅色"],["dark","深色"],["system","跟随系统"]].forEach(([m, lab]) => {{
        const b = document.createElement("button");
        b.type = "button";
        b.className = "pref-chip";
        b.dataset.mode = m;
        b.textContent = lab;
        b.addEventListener("click", () => {{
          writeConsolePrefsJson({{ theme: m }});
          try {{ localStorage.setItem(PALLAS_THEME_MODE_KEY, m); }} catch (e) {{}}
          applyPallasShellTheme(resolvePallasThemePreference(), {{ persist: false }});
          applyShellUiPrefsFromStorage();
          syncShellThemeToolbar();
          syncPrefsUi();
        }});
        tr.appendChild(b);
      }});
      const ar = document.getElementById("prefAccentRow");
      ACCENTS.forEach((a) => {{
        const b = document.createElement("button");
        b.type = "button";
        b.className = "pref-swatch";
        b.dataset.accent = a.id;
        b.title = a.label;
        b.style.backgroundColor = a.swatch;
        b.addEventListener("click", () => {{
          writeConsolePrefsJson({{ accentPreset: a.id }});
          applyShellUiPrefsFromStorage();
          syncPrefsUi();
        }});
        ar.appendChild(b);
      }});
      const rr = document.getElementById("prefRadiusRow");
      RADII.forEach((r) => {{
        const b = document.createElement("button");
        b.type = "button";
        b.className = "pref-chip";
        b.dataset.radius = r.id;
        b.textContent = r.label;
        b.addEventListener("click", () => {{
          writeConsolePrefsJson({{ radius: r.id }});
          applyShellUiPrefsFromStorage();
          syncPrefsUi();
        }});
        rr.appendChild(b);
      }});
      const dr = document.getElementById("prefDensityRow");
      [
        {{ key: "comfortable", title: "舒适", desc: "默认间距，阅读更轻松" }},
        {{ key: "compact", title: "紧凑", desc: "更小字号与行距，单屏更多信息" }},
      ].forEach((x) => {{
        const b = document.createElement("button");
        b.type = "button";
        b.dataset.density = x.key;
        b.innerHTML = "<span class=\\"t\\">" + x.title + "</span><span class=\\"d\\">" + x.desc + "</span>";
        b.addEventListener("click", () => {{
          writeConsolePrefsJson({{ density: x.key }});
          applyShellUiPrefsFromStorage();
          syncPrefsUi();
        }});
        dr.appendChild(b);
      }});
      const pr = document.getElementById("prefPollRow");
      POLLS.forEach((p) => {{
        const b = document.createElement("button");
        b.type = "button";
        b.className = "pref-chip";
        b.dataset.ms = String(p.value);
        b.textContent = p.label;
        b.addEventListener("click", () => {{
          try {{
            localStorage.setItem("pallas-dashboard-poll-ms", String(p.value));
            window.dispatchEvent(new Event("pallas-dashboard-poll-changed"));
          }} catch (e) {{}}
          syncPrefsUi();
        }});
        pr.appendChild(b);
      }});
      syncPrefsUi();
    }}
    wirePrefsPage();
    (function wireConsolePw() {{
      const b = document.getElementById("prefBtnSaveConsolePw");
      const a = document.getElementById("prefNewConsolePw");
      const c = document.getElementById("prefNewConsolePw2");
      const msg = document.getElementById("prefConsolePwMsg");
      if (!b || !a || !c) return;
      b.addEventListener("click", async () => {{
        const p1 = (a.value || "").trim();
        const p2 = (c.value || "").trim();
        if (!p1) return;
        if (p1 !== p2) {{ if (msg) msg.textContent = "两次输入不一致"; return; }}
        if (msg) msg.textContent = "提交中…";
        try {{
          await api("/api/security/console-login", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ new_password: p1 }}),
          }});
          a.value = "";
          c.value = "";
          if (msg) msg.textContent = "已保存";
        }} catch (e) {{
          if (msg) msg.textContent = String(e && e.message ? e.message : e);
        }}
      }});
    }})();
  </script>
</body>
</html>
"""


def render_dashboard(base_path: str, pallas_console_http_base: str = "/pallas") -> str:
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    common_api_js = _render_common_api_js()
    token_sync_js = _render_hidden_token_sync_js("backDash")
    shell_open = render_protocol_shell_open(
        path,
        pallas_console_http_base,
        active="dashboard",
        page_title="仪表盘",
        page_desc="协议账号与运行日志",
        topbar_actions=(
            '<button class="btn secondary" id="btnRefresh" type="button" onclick="refreshAccounts()">刷新</button>'
        ),
    )
    shell_close = render_protocol_shell_close(
        path, active="dashboard", pallas_console_http_base=pallas_console_http_base
    )
    new_href = html_escape(f"{path}/new", quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
{shell_head_assets(path)}  <title>仪表盘 · 协议端</title>
</head>
<body data-base-path="{html_escape(path, quote=True)}">
  <input type="hidden" id="token" value="" autocomplete="off" />
{shell_open}
    <div class="panel proto-panel proto-panel--accounts">
      <div class="panel__hd panel__hd--split proto-panel__hd">
        <h2 class="panel__title">协议账号</h2>
        <div class="proto-panel__toolbar">
        <a href="{new_href}" class="btn btn--primary proto-panel__hd-create">+ 创建账号</a>
        <div class="row-actions proto-panel__hd-batch">
        <button class="btn secondary" id="btnToggleAll" type="button" onclick="toggleAllAccounts(this)">一键启动全部</button>
        <button class="btn secondary" id="btnStopSelected" type="button" onclick="stopSelectedAccounts(this)" disabled>停止所选</button>
        <button class="btn secondary" id="btnRestartAll" type="button" onclick="restartAllAccounts(this)">一键重启全部</button>
        <span class="muted proto-panel__hd-count" id="selectedCountHint">已选 0</span>
        </div>
        </div>
      </div>
      <div class="panel__bd">
      <div class="kpi-grid" id="kpis"></div>
      <div class="toolbar">
        <input id="search" class="grow" placeholder="筛选：输入 QQ / 实例名 / 账号 ID" oninput="renderAccounts()" />
        <div class="view-toggle" role="tablist" aria-label="视图切换">
          <button id="btnViewCard" class="btn active" type="button" onclick="setViewMode('card')">卡片视图</button>
          <button id="btnViewTable" class="btn" type="button" onclick="setViewMode('table')">表格视图</button>
        </div>
        <label class="pill" style="cursor:pointer">
          <input id="selectAllFiltered" type="checkbox" style="margin-right:6px" onchange="toggleSelectAllFiltered(this.checked)" />
          全选当前列表
        </label>
        <label class="pill" style="cursor:pointer">
          <input id="autoRefresh" type="checkbox" checked style="margin-right:6px" />
          自动刷新日志
        </label>
      </div>
      <div id="cards" class="grid"></div>
      <div id="tableWrap" class="table-wrap" style="display:none"></div>
      </div>
    </div>

    <div class="panel proto-panel proto-panel--log">
      <div class="sl-runlog" id="nbLogCard">
        <div class="sl-runlog-hd">
          <div class="sl-runlog-titles">
            <h2 style="margin:0;font-size:1.05rem">运行日志<span class="sl-runlog-bad wait" id="nbLogStreamBadge">连接中</span></h2>
            <p style="margin:4px 0 0;font-size:0.78rem;color:var(--muted)" id="nbLogSubLine">
              最近 <span id="nbLogFilteredN">0</span> / <span id="nbLogTotalN">0</span> 条 · SSE 推送
            </p>
          </div>
          <div class="sl-runlog-tools">
            <input type="search" id="nbLogFilter" class="grow" placeholder="搜索消息 / 模块 / 级别" />
            <select id="nbLogScope" class="sl-runlog-scope" title="范围">
              <option value="all">全部</option>
              <option value="webui">控制台</option>
              <option value="protocol">协议</option>
            </select>
            <button type="button" class="btn secondary" id="nbLogPauseBtn">暂停</button>
            <button type="button" class="btn secondary" id="nbLogRefreshBtn">刷新</button>
            <button type="button" class="btn secondary" id="nbLogClearBtn">清空视图</button>
            <button type="button" class="btn secondary" id="nbLogCopyBtn">复制</button>
          </div>
        </div>
        <div class="sl-runlog-levels" id="nbLogLevels"></div>
        <div class="sl-runlog-viewport" id="nbLogViewport" tabindex="0" title="可框选复制；框选或聚焦时暂停自动滚动">
          <div class="sl-runlog-inner" id="nbLogRows"></div>
        </div>
      </div>
    </div>
{shell_close}
  <script>
    const basePath = {p};
{common_api_js}
{token_sync_js}
    let accountRows = [];
    let viewMode = "card";
    const selectedAccountIds = new Set();
    let lastAccountsRenderSig = "";
    let pendingSilentAccountsDom = false;
    const PALLAS_FAV_BOT_ACCOUNTS_KEY = "pallas_fav_bot_accounts_v1";
    let botFavoriteAccounts = readBotFavoriteAccounts();
    function readBotFavoriteAccounts() {{
      try {{
        const raw = localStorage.getItem(PALLAS_FAV_BOT_ACCOUNTS_KEY);
        if (!raw) return new Set();
        const data = JSON.parse(raw);
        if (!Array.isArray(data)) return new Set();
        const s = new Set();
        for (const x of data) {{
          const n = typeof x === "number" ? x : parseInt(String(x), 10);
          if (Number.isFinite(n) && n > 0) s.add(Math.floor(n));
        }}
        return s;
      }} catch (e) {{
        return new Set();
      }}
    }}
    function writeBotFavoriteAccounts(s) {{
      try {{
        localStorage.setItem(PALLAS_FAV_BOT_ACCOUNTS_KEY, JSON.stringify([...s].sort((a, b) => a - b)));
      }} catch (e) {{}}
    }}
    function accountFavoriteNumber(a) {{
      const q = parseInt(String(a?.qq ?? a?.id ?? "").replace(/\\s/g, ""), 10);
      if (Number.isFinite(q) && q > 0) return Math.floor(q);
      return null;
    }}
    function isFavoriteAccount(a) {{
      const n = accountFavoriteNumber(a);
      return n != null && botFavoriteAccounts.has(n);
    }}
    function toggleFavoriteAccountById(id, ev) {{
      if (ev) {{
        ev.preventDefault();
        ev.stopPropagation();
      }}
      const a = (accountRows || []).find((x) => String(x.id) === String(id));
      if (!a) return;
      const n = accountFavoriteNumber(a);
      if (n == null) return;
      const s = new Set(botFavoriteAccounts);
      if (s.has(n)) s.delete(n);
      else s.add(n);
      botFavoriteAccounts = s;
      writeBotFavoriteAccounts(s);
      accountRows = sortAccountsDashboard(accountRows);
      renderAccounts();
    }}
    if (typeof window !== "undefined") {{
      window.addEventListener("storage", (ev) => {{
        if (ev.key !== PALLAS_FAV_BOT_ACCOUNTS_KEY) return;
        botFavoriteAccounts = readBotFavoriteAccounts();
        accountRows = sortAccountsDashboard(accountRows);
        renderAccounts();
      }});
    }}
    function accountFavStarHtml(a) {{
      const n = accountFavoriteNumber(a);
      if (n == null) return "";
      const on = botFavoriteAccounts.has(n);
      const id = escHtmlDash(String(a.id));
      const title = on ? "取消收藏" : "收藏";
      return `<button type="button" class="inst-fav-star" aria-pressed="${{on ? "true" : "false"}}" title="${{title}}" onclick="toggleFavoriteAccountById('${{id}}', event)">★</button>`;
    }}
    function accountsListSignature(rows) {{
      return (rows || []).map((a) => {{
        const id = String(a.id ?? a.qq ?? "").trim();
        const qq = String(a.qq ?? "").trim();
        const connected = a.connected ? "1" : "0";
        const running = (a.process_running || a.running) ? "1" : "0";
        return `${{id}}:${{qq}}:${{connected}}:${{running}}`;
      }}).join("|");
    }}
    function flushPendingAccountsDom() {{
      if (!pendingSilentAccountsDom) return;
      pendingSilentAccountsDom = false;
      const sig = accountsListSignature(accountRows);
      if (sig === lastAccountsRenderSig) return;
      lastAccountsRenderSig = sig;
      renderKpis(accountRows);
      pruneSelectedAccountIds();
      renderAccounts();
      updateToggleAllButton();
    }}
    onProtoMainInnerScrollEnd(flushPendingAccountsDom);
    function setBusy(el, busy, idleText = "刷新", busyText = "刷新中...") {{
      if (!el) return;
      el.disabled = !!busy;
      el.classList.toggle("busy", !!busy);
      if (typeof el.textContent === "string") el.textContent = busy ? busyText : idleText;
    }}
    (function initPagePrefs() {{
      initPallasShellThemeFromStorage();
      applyShellUiPrefsFromStorage();
      initProtocolShellChrome();
    }})();
    function notify(msg, level = "ok") {{
      const host = document.getElementById("statusbar");
      const el = document.createElement("div");
      el.className = `toast ${{level}}`;
      el.textContent = String(msg || "");
      host.appendChild(el);
      setTimeout(() => el.remove(), 4200);
    }}
    function nbFormatTime(iso) {{
      try {{
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return String(iso || "");
        return d.toLocaleTimeString();
      }} catch (e) {{ return String(iso || ""); }}
    }}
    const NB_LEVELS = ["debug", "info", "success", "warn", "error"];
    let nbLogEntries = [];
    let nbLogPaused = false;
    let nbLogFilter = "";
    let nbLogLevels = new Set(NB_LEVELS);
    let nbLogEs = null;
    function nbStreamBadge(text, kind) {{
      const el = document.getElementById("nbLogStreamBadge");
      if (!el) return;
      el.textContent = text;
      el.className = "sl-runlog-bad " + (kind === "ok" ? "ok" : kind === "err" ? "err" : "wait");
    }}
    function nbLevelUiClass(lv) {{
      const u = String(lv || "").toLowerCase();
      if (u === "debug") return "sl-lv-debug";
      if (u === "success") return "sl-lv-success";
      if (u === "warn") return "sl-lv-warn";
      if (u === "error") return "sl-lv-error";
      return "sl-lv-info";
    }}
    function nbFiltered() {{
      const f = (nbLogFilter || "").trim().toLowerCase();
      return nbLogEntries.filter((x) => {{
        if (!nbLogLevels.has(String(x.level || "").toLowerCase())) return false;
        if (!f) return true;
        const m = String(x.message || "").toLowerCase();
        const sc = String(x.scope || "").toLowerCase();
        const lv = String(x.level || "").toLowerCase();
        return m.includes(f) || sc.includes(f) || lv.includes(f);
      }});
    }}
    function nbShouldPauseDom() {{
      const vp = document.getElementById("nbLogViewport");
      if (!vp) return false;
      return shouldPauseLiveLogDomWrite(vp);
    }}
    function nbRender() {{
      const rows = document.getElementById("nbLogRows");
      const sub = document.getElementById("nbLogFilteredN");
      const tot = document.getElementById("nbLogTotalN");
      if (tot) tot.textContent = String(nbLogEntries.length);
      const list = nbFiltered();
      if (sub) sub.textContent = String(list.length);
      if (!rows) return;
      if (!list.length) {{
        rows.innerHTML = '<div class="sl-runlog-empty">暂无日志</div>';
        return;
      }}
      rows.innerHTML = list.map((x) => {{
        const lv = String(x.level || "").toUpperCase();
        const t = nbFormatTime(x.time);
        const sc = escHtmlDash(x.scope || "");
        const msg = escHtmlDash(x.message || "");
        const lc = nbLevelUiClass(x.level);
        return `<div class="sl-runlog-row"><span class="sl-runlog-t">${{t}}</span><span class="sl-runlog-lv ${{lc}}">${{lv}}</span><span class="sl-runlog-sc">[${{sc}}]</span><span class="sl-runlog-msg">${{msg}}</span></div>`;
      }}).join("");
    }}
    let nbLogRenderDeferred = false;
    let nbRenderScheduled = 0;
    function scheduleNbRender() {{
      if (nbRenderScheduled) return;
      if (isProtoMainInnerScrolling() || nbShouldPauseDom()) {{
        nbLogRenderDeferred = true;
        return;
      }}
      nbRenderScheduled = requestAnimationFrame(() => {{
        nbRenderScheduled = 0;
        if (nbShouldPauseDom()) {{
          nbLogRenderDeferred = true;
          return;
        }}
        nbRender();
        nbScrollToEnd();
      }});
    }}
    function flushDeferredNbLogRender() {{
      if (!nbLogRenderDeferred) return;
      nbLogRenderDeferred = false;
      scheduleNbRender();
    }}
    onProtoMainInnerScrollEnd(flushDeferredNbLogRender);
    function nbScrollToEnd() {{
      if (nbLogPaused) return;
      if (nbShouldPauseDom()) return;
      const vp = document.getElementById("nbLogViewport");
      if (vp) vp.scrollTop = vp.scrollHeight;
    }}
    function nbInitLevelPills() {{
      const host = document.getElementById("nbLogLevels");
      if (!host) return;
      host.innerHTML = NB_LEVELS.map((lv) =>
        `<button type="button" data-nb-lv="${{lv}}" class="on">${{String(lv).toUpperCase()}}</button>`
      ).join("");
      host.querySelectorAll("[data-nb-lv]").forEach((btn) => {{
        btn.addEventListener("click", () => {{
          const lv = btn.getAttribute("data-nb-lv");
          if (nbLogLevels.has(lv)) nbLogLevels.delete(lv);
          else nbLogLevels.add(lv);
          btn.classList.toggle("on", nbLogLevels.has(lv));
          btn.classList.toggle("off", !nbLogLevels.has(lv));
          nbRender();
        }});
      }});
    }}
    async function nbLoadInitial() {{
      const scopeEl = document.getElementById("nbLogScope");
      const sc = scopeEl ? scopeEl.value : "all";
      const data = await api(`/api/nonebot-logs?lines=180&scope=${{encodeURIComponent(sc)}}`);
      nbLogEntries = Array.isArray(data.entries) ? data.entries.slice() : [];
      nbRender();
      nbScrollToEnd();
    }}
    function nbClear() {{
      if (!confirm("清空当前日志视图？仅影响浏览器展示，不清服务端缓冲。")) return;
      nbLogEntries = [];
      nbRender();
    }}
    function nbCopy() {{
      const lines = nbFiltered().map((x) =>
        `${{nbFormatTime(x.time)}} ${{String(x.level || "").toUpperCase()}} [${{x.scope}}] ${{x.message}}`
      );
      const t = lines.join("\\n");
      if (!String(t).trim()) {{ notify("当前无可复制内容", "warn"); return; }}
      navigator.clipboard.writeText(t).then(() => notify("已复制", "ok")).catch((e) => notify(String(e.message || e), "err"));
    }}
    function nbStopSse() {{
      if (nbLogEs) {{
        try {{ nbLogEs.close(); }} catch (e) {{}}
        nbLogEs = null;
      }}
    }}
    function nbStartSse() {{
      nbStopSse();
      const tok = getSessionToken();
      const scopeEl = document.getElementById("nbLogScope");
      const sc = scopeEl ? scopeEl.value : "all";
      let url = `${{basePath}}/api/nonebot-logs/stream?scope=${{encodeURIComponent(sc)}}`;
      if (tok) url += `&token=${{encodeURIComponent(tok)}}`;
      nbStreamBadge("连接中", "wait");
      const es = new EventSource(url);
      nbLogEs = es;
      es.onopen = () => nbStreamBadge("实时", "ok");
      es.onerror = () => nbStreamBadge("重连中", "err");
      es.onmessage = (ev) => {{
        try {{
          const row = JSON.parse(ev.data);
          if (row && row.type === "ready") return;
          if (!row || typeof row.id !== "number") return;
          if (nbLogPaused) return;
          nbLogEntries = [...nbLogEntries.filter((it) => it.id !== row.id), row].slice(-1000);
          scheduleNbRender();
        }} catch (e) {{}}
      }};
    }}
    function nbWireRunlogUi() {{
      nbInitLevelPills();
      document.getElementById("nbLogFilter")?.addEventListener("input", (e) => {{
        nbLogFilter = (e.target && e.target.value) || "";
        nbRender();
      }});
      document.getElementById("nbLogPauseBtn")?.addEventListener("click", () => {{
        nbLogPaused = !nbLogPaused;
        const b = document.getElementById("nbLogPauseBtn");
        if (b) b.textContent = nbLogPaused ? "继续" : "暂停";
        if (!nbLogPaused) nbScrollToEnd();
      }});
      document.getElementById("nbLogRefreshBtn")?.addEventListener("click", () => {{
        nbLoadInitial().catch((e) => notify(e.message || e, "err"));
      }});
      document.getElementById("nbLogClearBtn")?.addEventListener("click", nbClear);
      document.getElementById("nbLogCopyBtn")?.addEventListener("click", nbCopy);
      document.getElementById("nbLogScope")?.addEventListener("change", () => {{
        nbLoadInitial().catch(() => {{}});
        nbStartSse();
      }});
    }}
    function openAccount(id) {{
      location.href = `${{basePath}}/account/${{encodeURIComponent(id)}}`;
    }}
    function escHtmlDash(s) {{
      return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }}
    function qqAvatarUrl(uin) {{
      const n = String(uin ?? "").replace(/\\s/g, "");
      if (!/^\\d+$/.test(n)) return "";
      return `https://q1.qlogo.cn/g?b=qq&nk=${{encodeURIComponent(n)}}&s=160`;
    }}
    function accCardAvatarHtml(qqOrId) {{
      const q = String(qqOrId ?? "").trim();
      const url = qqAvatarUrl(q);
      const label = escHtmlDash(q ? q.slice(-2) : "?");
      if (!url) {{
        return `<div class="acc-card-avatar"><span class="acc-card-avatar-fallback">${{label}}</span></div>`;
      }}
      return `<div class="acc-card-avatar"><img src="${{url}}" alt="" width="48" height="48" loading="lazy" decoding="async" onerror="this.style.display='none';var f=this.nextElementSibling;if(f)f.style.display='flex';" /><span class="acc-card-avatar-fallback" style="display:none">${{label}}</span></div>`;
    }}
    function getFilteredAccountRows() {{
      const q = (document.getElementById("search").value || "").trim().toLowerCase();
      if (!q) return accountRows;
      return accountRows.filter((a) => {{
        return String(a.id || "").toLowerCase().includes(q)
          || String(a.qq || "").toLowerCase().includes(q)
          || String(a.display_name || "").toLowerCase().includes(q);
      }});
    }}
    function accountSelectCheckbox(id) {{
      const on = selectedAccountIds.has(id) ? " checked" : "";
      return `<label class="acc-select" onclick="event.stopPropagation()"><input type="checkbox"${{on}} onchange="toggleAccountSelected('${{escHtmlDash(id)}}', this.checked)" aria-label="选择账号" /><span class="acc-select__box" aria-hidden="true"></span></label>`;
    }}
    function toggleAccountSelected(id, checked) {{
      if (checked) selectedAccountIds.add(id);
      else selectedAccountIds.delete(id);
      updateSelectionUi();
      syncSelectAllCheckbox();
    }}
    function syncSelectAllCheckbox() {{
      const box = document.getElementById("selectAllFiltered");
      if (!box) return;
      const rows = getFilteredAccountRows();
      if (!rows.length) {{
        box.checked = false;
        box.indeterminate = false;
        return;
      }}
      const n = rows.filter((a) => selectedAccountIds.has(a.id)).length;
      box.checked = n > 0 && n === rows.length;
      box.indeterminate = n > 0 && n < rows.length;
    }}
    function toggleSelectAllFiltered(checked) {{
      getFilteredAccountRows().forEach((a) => {{
        if (checked) selectedAccountIds.add(a.id);
        else selectedAccountIds.delete(a.id);
      }});
      renderAccounts();
      updateSelectionUi();
    }}
    function updateSelectionUi() {{
      const n = selectedAccountIds.size;
      const btn = document.getElementById("btnStopSelected");
      if (btn) btn.disabled = n === 0;
      const hint = document.getElementById("selectedCountHint");
      if (hint) hint.textContent = "已选 " + n;
    }}
    function pruneSelectedAccountIds() {{
      const valid = new Set((accountRows || []).map((a) => a.id));
      for (const id of [...selectedAccountIds]) {{
        if (!valid.has(id)) selectedAccountIds.delete(id);
      }}
      updateSelectionUi();
      syncSelectAllCheckbox();
    }}
    async function stopSelectedAccounts(btn) {{
      const ids = [...selectedAccountIds];
      if (!ids.length) {{
        notify("请先勾选要停止的账号", "warn");
        return;
      }}
      btnLoad(btn, "停止中…");
      try {{
        await Promise.all(ids.map((id) => api(`/api/accounts/${{id}}/stop`, {{ method: "POST" }})));
        await refreshAccounts({{ silent: true }});
        notify("已停止 " + ids.length + " 个账号", "warn");
      }} catch (e) {{
        notify(e.message || e, "err");
      }} finally {{
        btnReset(btn);
      }}
    }}
    function renderKpis(rows) {{
      const total = rows.length;
      const running = rows.filter((x) => !!x.running).length;
      const connected = rows.filter((x) => !!x.connected).length;
      const bad = rows.filter((x) => !x.launch_ready).length;
      const el = document.getElementById("kpis");
      el.innerHTML = `
        <div class="kpi"><div class="k">账号总数</div><div class="v">${{total}}</div></div>
        <div class="kpi"><div class="k">运行中</div><div class="v">${{running}}</div></div>
        <div class="kpi"><div class="k">已连接</div><div class="v">${{connected}}</div></div>
        <div class="kpi"><div class="k">异常</div><div class="v">${{bad}}</div></div>`;
    }}
    function renderAccounts() {{
      const mode = viewMode || "card";
      const rows = getFilteredAccountRows();
      const g = document.getElementById("cards");
      const tw = document.getElementById("tableWrap");
      g.innerHTML = "";
      tw.innerHTML = "";
      if (mode === "table") {{
        g.style.display = "none";
        tw.style.display = "block";
        const body = rows.map((a) => {{
          const st = a.connected ? "已连接" : (a.process_running ? "运行中" : (a.launch_ready ? "已停止" : "异常"));
          const cls = a.connected ? "ok" : (a.process_running ? "run" : (a.launch_ready ? "stop" : "bad"));
          const pb = String(a.protocol_backend || "napcat").toLowerCase();
          const slPw = String(a.snowluma_runtime_webui_password || "").trim();
          const wtok = String(a.webui_token || "").replace(/</g, "");
          const webuiCell = a.native_webui_url
            ? (pb === "snowluma"
              ? `<div class="acc-card-webui" style="margin:0;padding:0;border:0"><div class="acc-card-webui-line" style="margin:0">`
                + `<a href="${{a.native_webui_url}}" target="_blank" rel="noopener">SnowLuma WebUI</a></div>`
                + ((slPw
                  ? `<div class="acc-card-webui-line" style="margin-top:4px"><span class="muted">临时密码</span> <span class="mono">${{escHtmlDash(slPw)}}</span> `
                    + `<button type="button" class="btn secondary" style="font-size:0.72rem;padding:2px 6px" data-copy-plain="${{encodeURIComponent(slPw)}}">复制</button></div>`
                  : ""))
                + `</div>`
              : `<div class="acc-card-webui" style="margin:0;padding:0;border:0"><div class="acc-card-webui-line" style="margin:0">`
                + `<a href="${{a.native_webui_url}}" target="_blank" rel="noopener">NapCat WebUI</a></div>`
                + `<div class="acc-card-webui-line" style="margin-top:4px"><span class="muted">token</span> <span class="mono">${{escHtmlDash(wtok)}}</span></div></div>`)
            : "—";
          const running = !!a.process_running;
          const startStopBtn = running
            ? `<button class="btn secondary" type="button" onclick="stopAccount('${{a.id}}',this)">停止</button>`
            : `<button class="btn secondary" type="button" onclick="startAccount('${{a.id}}',this)">启动</button>`;
          return `<tr>
            <td data-label="选择" class="acc-td-select">${{accountSelectCheckbox(a.id)}}</td>
            <td data-label="实例名"><span class="acc-td-val">${{a.display_name || a.qq || a.id}}</span></td>
            <td data-label="QQ号"><span class="acc-td-val">${{a.qq || a.id}}</span></td>
            <td data-label="版本"><span class="acc-td-val">${{a.runtime_version || "未知"}}<div class="muted" style="font-size:0.75rem">${{a.runtime_source || "未知来源"}}</div></span></td>
            <td data-label="状态"><span class="acc-td-val"><span class="tag ${{cls}}">${{st}}</span></span></td>
            <td data-label="内置 WebUI"><span class="acc-td-val">${{webuiCell}}</span></td>
            <td data-label="操作" class="acc-td-actions">
              <div class="row">
                <button class="btn acc-card-console-btn" type="button" onclick="openAccount('${{a.id}}')">控制台</button>
                ${{accountFavStarHtml(a)}}
                ${{startStopBtn}}
                <button class="btn secondary" type="button" onclick="restartAccount('${{a.id}}',this)">重启</button>
              </div>
            </td>
          </tr>`;
        }}).join("");
        tw.innerHTML = `<table class="acc-table acc-table--responsive"><thead><tr>
          <th class="acc-th-select">选择</th><th>实例名</th><th>QQ号</th><th>版本</th><th>状态</th><th>内置 WebUI</th><th>操作</th>
        </tr></thead><tbody>${{body || `<tr class="acc-table-empty"><td colspan="7" class="muted">无匹配账号</td></tr>`}}</tbody></table>`;
        syncSelectAllCheckbox();
        return;
      }}
      g.style.display = "grid";
      tw.style.display = "none";
      rows.forEach((a) => {{
        const st = a.connected ? "已连接" : (a.process_running ? "运行中" : (a.launch_ready ? "已停止" : "异常"));
        const cls = a.connected ? "ok" : (a.process_running ? "run" : (a.launch_ready ? "stop" : "bad"));
        const pb = String(a.protocol_backend || "napcat").toLowerCase();
        const card = document.createElement("div");
        card.className = "card";
        const wu = a.native_webui_url || "";
        const wtok = (a.webui_token || "").replace(/</g, "");
        const slPw = String(a.snowluma_runtime_webui_password || "").trim();
        const webuiBlock = !wu
          ? ""
          : (pb === "snowluma"
            ? (`<div class="acc-card-webui"><div class="acc-card-webui-hd">内置 WebUI</div>`
              + `<div class="acc-card-webui-line"><a href="${{wu}}" target="_blank" rel="noopener">打开 SnowLuma 内置 WebUI</a></div>`
              + (slPw
                ? (`<div class="acc-card-webui-line"><span class="muted">临时密码</span> <span class="mono">${{escHtmlDash(slPw)}}</span> `
                  + `<button type="button" class="btn secondary" style="font-size:0.78rem;padding:4px 8px;margin-left:6px;vertical-align:middle" data-copy-plain="${{encodeURIComponent(slPw)}}">复制</button></div>`)
                : "")
              + `</div>`)
            : (`<div class="acc-card-webui"><div class="acc-card-webui-hd">内置 WebUI</div>`
              + `<div class="acc-card-webui-line"><a href="${{wu}}" target="_blank" rel="noopener">打开 NapCat 内置 WebUI</a></div>`
              + `<div class="acc-card-webui-line"><span class="muted">token</span> <span class="mono">${{escHtmlDash(wtok)}}</span></div></div>`));
        const running = !!a.process_running;
        const startStopBtn = running
          ? `<button class="btn secondary" type="button" onclick="stopAccount('${{a.id}}',this)">停止</button>`
          : `<button class="btn secondary" type="button" onclick="startAccount('${{a.id}}',this)">启动</button>`;
        card.innerHTML = `
          <div class="acc-card-top">
            ${{accountSelectCheckbox(a.id)}}
            ${{accCardAvatarHtml(a.qq || a.id)}}
            <div class="acc-card-top-main">
              <h3 class="acc-card-hd">${{a.display_name || a.id}}</h3>
              <div class="acc-card-status"><span class="tag ${{cls}}">${{st}}</span></div>
            </div>
            ${{accountFavStarHtml(a)}}
            <button class="btn acc-card-console-btn" type="button" onclick="openAccount('${{a.id}}')">控制台</button>
          </div>
          <p class="acc-card-meta">QQ：${{a.qq || a.id}}</p>
          <p class="acc-card-meta">版本：${{a.runtime_version || "未知"}}</p>
          <p class="acc-card-meta">归属：${{a.runtime_source || "未知来源"}}</p>
          ${{webuiBlock}}
          <div class="row" style="margin-top:10px">
            ${{startStopBtn}}
            <button class="btn secondary" type="button" onclick="restartAccount('${{a.id}}',this)">重启</button>
            <button class="btn danger" type="button" onclick="deleteAccount('${{a.id}}', this)">删除</button>
          </div>`;
        g.appendChild(card);
      }});
      syncSelectAllCheckbox();
    }}
    function setViewMode(mode) {{
      viewMode = mode === "table" ? "table" : "card";
      document.getElementById("btnViewCard").classList.toggle("active", viewMode === "card");
      document.getElementById("btnViewTable").classList.toggle("active", viewMode === "table");
      renderAccounts();
    }}
    async function refreshAccounts(opts) {{
      const silent = !!(opts && opts.silent);
      const force = !!(opts && opts.force) || !silent;
      const btn = document.getElementById("btnRefresh");
      if (!silent) setBusy(btn, true, "刷新", "刷新中...");
      try {{
        const data = await api("/api/accounts");
        accountRows = sortAccountsDashboard(data.accounts || []);
        const sig = accountsListSignature(accountRows);
        if (!force && sig === lastAccountsRenderSig) return;
        if (silent && isProtoMainInnerScrolling()) {{
          pendingSilentAccountsDom = true;
          return;
        }}
        pendingSilentAccountsDom = false;
        lastAccountsRenderSig = sig;
        renderKpis(accountRows);
        pruneSelectedAccountIds();
        renderAccounts();
        updateToggleAllButton();
        if (!silent) notify("已刷新账号列表", "ok");
      }} finally {{
        if (!silent) setBusy(btn, false, "刷新", "刷新中...");
      }}
    }}
    function btnLoad(btn, text) {{
      if (!btn) return;
      btn.disabled = true;
      btn.dataset.idle = btn.textContent;
      btn.innerHTML = `<span class="spinner"></span>${{text}}`;
    }}
    function btnReset(btn) {{
      if (!btn) return;
      btn.disabled = false;
      btn.textContent = btn.dataset.idle || btn.textContent;
    }}
    function isAccountRunning(a) {{
      return !!(a && a.process_running);
    }}
    function sortAccountsDashboard(rows) {{
      return [...(rows || [])].sort((a, b) => {{
        const fa = accountFavoriteNumber(a);
        const fb = accountFavoriteNumber(b);
        const favA = fa != null && botFavoriteAccounts.has(fa) ? 1 : 0;
        const favB = fb != null && botFavoriteAccounts.has(fb) ? 1 : 0;
        if (favA !== favB) return favB - favA;
        const ca = a.connected === true ? 1 : 0;
        const cb = b.connected === true ? 1 : 0;
        if (ca !== cb) return cb - ca;
        const an = String(a?.display_name || a?.qq || a?.id || "");
        const bn = String(b?.display_name || b?.qq || b?.id || "");
        const cmp = an.localeCompare(bn, "zh-CN", {{ sensitivity: "base", numeric: true }});
        if (cmp !== 0) return cmp;
        return String(a?.qq ?? a?.id ?? "").localeCompare(String(b?.qq ?? b?.id ?? ""), "zh-CN", {{ numeric: true }});
      }});
    }}
    function updateToggleAllButton() {{
      const btn = document.getElementById("btnToggleAll");
      if (!btn) return;
      const allRunning = accountRows.length > 0 && accountRows.every((a) => isAccountRunning(a));
      btn.textContent = allRunning ? "一键停止全部" : "一键启动全部";
    }}
    async function startAccount(id, btn) {{
      btnLoad(btn, "启动中…");
      try {{ await api(`/api/accounts/${{id}}/start`, {{ method: "POST" }}); await refreshAccounts({{ silent: true }}); notify(`已启动 ${{id}}`, "ok"); }}
      catch (e) {{ notify(e.message || e, "err"); }}
      finally {{ btnReset(btn); }}
    }}
    async function stopAccount(id, btn) {{
      btnLoad(btn, "停止中…");
      try {{ await api(`/api/accounts/${{id}}/stop`, {{ method: "POST" }}); await refreshAccounts({{ silent: true }}); notify(`已停止 ${{id}}`, "warn"); }}
      catch (e) {{ notify(e.message || e, "err"); }}
      finally {{ btnReset(btn); }}
    }}
    async function restartAccount(id, btn) {{
      btnLoad(btn, "重启中…");
      try {{ await api(`/api/accounts/${{id}}/restart`, {{ method: "POST" }}); await refreshAccounts({{ silent: true }}); notify(`已重启 ${{id}}`, "ok"); }}
      catch (e) {{ notify(e.message || e, "err"); }}
      finally {{ btnReset(btn); }}
    }}
    async function toggleAllAccounts(btn) {{
      if (!accountRows.length) {{
        notify("当前没有可操作实例", "warn");
        return;
      }}
      const allRunning = accountRows.every((a) => isAccountRunning(a));
      const action = allRunning ? "stop" : "start";
      const loadingText = allRunning ? "停止全部中…" : "启动全部中…";
      btnLoad(btn, loadingText);
      try {{
        await Promise.all(accountRows.map((a) => api(`/api/accounts/${{a.id}}/${{action}}`, {{ method: "POST" }})));
        await refreshAccounts({{ silent: true }});
        notify(allRunning ? "已停止全部实例" : "已启动全部实例", allRunning ? "warn" : "ok");
      }} catch (e) {{
        notify(e.message || e, "err");
      }} finally {{
        btnReset(btn);
        updateToggleAllButton();
      }}
    }}
    async function restartAllAccounts(btn) {{
      if (!accountRows.length) {{
        notify("当前没有可操作实例", "warn");
        return;
      }}
      btnLoad(btn, "重启全部中…");
      try {{
        await Promise.all(accountRows.map((a) => api(`/api/accounts/${{a.id}}/restart`, {{ method: "POST" }})));
        await refreshAccounts({{ silent: true }});
        notify("已重启全部实例", "ok");
      }} catch (e) {{
        notify(e.message || e, "err");
      }} finally {{
        btnReset(btn);
        updateToggleAllButton();
      }}
    }}
    async function deleteAccount(id, btn) {{
      if (!confirm("确定删除 " + id + " ?")) return;
      btnLoad(btn, "删除中…");
      try {{
        await api(`/api/accounts/${{id}}`, {{ method: "DELETE" }});
        await refreshAccounts({{ silent: true }});
        notify(`已删除 ${{id}}`, "warn");
      }} catch (e) {{
        notify(e.message || e, "err");
      }} finally {{
        btnReset(btn);
      }}
    }}
    refreshAccounts({{ silent: true }}).catch((e) => notify(e.message || e, "err"));
    nbWireRunlogUi();
    setTimeout(() => {{
      nbLoadInitial().then(() => nbStartSse()).catch((e) => notify(e.message || e, "err"));
    }}, 350);
    setInterval(() => {{
      if (!document.getElementById("autoRefresh").checked) return;
      if (document.hidden || isProtoMainInnerScrolling()) return;
      nbLoadInitial().catch(() => {{}});
    }}, 8000);
    (function() {{
      const poll = parseInt(localStorage.getItem("pallas-dashboard-poll-ms") || "10000", 10);
      const ms = Number.isFinite(poll) ? Math.max(poll, 5000) : 10000;
      setInterval(() => {{
        if (document.hidden || isProtoMainInnerScrolling()) return;
        refreshAccounts({{ silent: true }}).catch(() => {{}});
      }}, ms);
    }})();
  </script>
  <div id="statusbar" class="statusbar"></div>
</body>
</html>
"""


def render_import_page(base_path: str, pallas_console_http_base: str = "/pallas") -> str:
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    common_api_js = _render_common_api_js()
    token_sync_js = _render_hidden_token_sync_js("backDash")
    shell_open = render_protocol_shell_open(
        path, pallas_console_http_base, active="import", page_title="导入账号", page_desc="批量导入旧协议端数据"
    )
    shell_close = render_protocol_shell_close(path, active="import", pallas_console_http_base=pallas_console_http_base)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
{shell_head_assets(path)}  <title>导入账号 · 协议端</title>
  <style>
.result-row {{ display:flex; gap:8px; align-items:baseline; padding:6px 0; border-bottom:1px solid var(--bd); font-size:0.88rem; }}
.result-row:last-child {{ border-bottom:none; }}
.result-row .folder {{ font-weight:600; min-width:160px; }}
.result-row .detail {{ color:var(--muted); }}
  </style>
</head>
<body>
  <input type="hidden" id="token" value="" autocomplete="off" />
  {shell_open}
    <div class="proto-form-page">
    <div class="card">
      <h3 style="margin:0 0 4px">批量导入旧协议端账号</h3>
      <p class="muted" style="margin:0 0 16px">
        扫描指定目录下的账号文件夹（格式：<code>&lt;昵称&gt;/config/</code>），
        从 <code>onebot_*.json</code> 提取 QQ 号，原地注册为受管账号，
        并将 <code>QQ/</code> 复制到 <code>.config/QQ/</code>。
      </p>

      <div class="field">
        <label>账号文件夹根目录（服务器绝对路径）</label>
        <input id="sourceDir" autocomplete="off" placeholder="/data/old_accounts" style="width:100%" />
      </div>

      <div class="field">
        <label>WS 连接地址（留空则使用 .env 默认值）</label>
        <input id="wsUrl" autocomplete="off" placeholder="ws://127.0.0.1:8088/onebot/v11/ws" style="width:100%" />
      </div>

      <div class="field">
        <label>WS Token（留空则不鉴权）</label>
        <input id="wsToken" type="password" autocomplete="off" style="width:100%" />
      </div>

      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
        <label style="display:flex;align-items:center;gap:6px;font-size:0.88rem;cursor:pointer">
          <input type="checkbox" id="dryRun" /> 仅预览（不写入）
        </label>
        <label style="display:flex;align-items:center;gap:6px;font-size:0.88rem;cursor:pointer">
          <input type="checkbox" id="skipExisting" checked /> 跳过已存在账号
        </label>
      </div>

      <div class="row">
        <button class="btn" id="btnImport" type="button" onclick="doImport()">开始导入</button>
      </div>
    </div>

    <div id="resultSection" class="proto-form-results" style="display:none">
      <div class="kpi-grid" id="resultKpis"></div>
      <div class="card" style="margin-top:12px">
        <h3 style="margin:0 0 10px">导入结果</h3>
        <div id="resultImported"></div>
        <div id="resultSkipped" style="margin-top:10px"></div>
        <div id="resultFailed" style="margin-top:10px"></div>
      </div>
    </div>
    </div>
{shell_close}

  <script>
    const basePath = {p};
{token_sync_js}
{common_api_js}
    initPallasShellThemeFromStorage();

    function renderRows(containerId, items, labelFn, cls) {{
      const el = document.getElementById(containerId);
      if (!items || !items.length) {{ el.innerHTML = ""; return; }}
      el.innerHTML = `<div style="font-size:0.78rem;color:var(--muted);font-weight:700;margin-bottom:6px;text-transform:uppercase">${{cls}}</div>`
        + items.map((r) => `<div class="result-row"><span class="folder">${{r.folder || ""}}</span><span class="detail">${{labelFn(r)}}</span></div>`).join("");
    }}

    async function doImport() {{
      const src = document.getElementById("sourceDir").value.trim();
      if (!src) {{ alert("请填写账号文件夹根目录"); return; }}
      const btn = document.getElementById("btnImport");
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span>导入中…';
      document.getElementById("resultSection").style.display = "none";
      try {{
        const body = {{
          source_dir: src,
          dry_run: document.getElementById("dryRun").checked,
          skip_existing: document.getElementById("skipExisting").checked,
          ws_url: document.getElementById("wsUrl").value.trim(),
          ws_token: document.getElementById("wsToken").value,
        }};
        const data = await api("/api/accounts/import", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(body),
        }});
        const imp = data.imported || [];
        const skp = data.skipped || [];
        const fld = data.failed || [];
        document.getElementById("resultKpis").innerHTML = `
          <div class="kpi"><div class="k">已导入</div><div class="v" style="color:var(--ok)">${{imp.length}}</div></div>
          <div class="kpi"><div class="k">已跳过</div><div class="v" style="color:var(--warn)">${{skp.length}}</div></div>
          <div class="kpi"><div class="k">失败</div><div class="v" style="color:var(--err)">${{fld.length}}</div></div>`;
        renderRows("resultImported", imp,
          (r) => `QQ: ${{r.qq}}  端口: ${{r.webui_port}}${{r.qq_copied_to ? "  QQ/ → .config/QQ/" : ""}}`,
          "已导入");
        renderRows("resultSkipped", skp,
          (r) => r.qq ? `QQ: ${{r.qq}}  (${{r.reason}})` : r.reason,
          "已跳过");
        renderRows("resultFailed", fld,
          (r) => r.reason,
          "失败");
        document.getElementById("resultSection").style.display = "block";
        if (imp.length && !body.dry_run) {{
          setTimeout(() => location.href = document.getElementById("backDash").href, 1800);
        }}
      }} catch (e) {{
        alert(e.message || String(e));
      }} finally {{
        btn.disabled = false;
        btn.textContent = "开始导入";
      }}
    }}
  </script>
  <div id="statusbar" class="statusbar"></div>
</body>
</html>
"""


def render_new_account_page(base_path: str, pallas_console_http_base: str = "/pallas") -> str:
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    common_api_js = _render_common_api_js()
    token_sync_js = _render_hidden_token_sync_js("backDash")
    shell_open = render_protocol_shell_open(
        path, pallas_console_http_base, active="new", page_title="创建账号", page_desc="新建协议实例"
    )
    shell_close = render_protocol_shell_close(path, active="new", pallas_console_http_base=pallas_console_http_base)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
{shell_head_assets(path)}  <title>新建账号 · 协议端</title>
</head>
<body data-base-path="{html_escape(path, quote=True)}">
  <input type="hidden" id="token" value="" autocomplete="off" />
  {shell_open}
    <div class="proto-form-page proto-form-page--full">
    <div class="card">
      <div class="field"><label>QQ 号</label>
        <input id="qq" inputmode="numeric" autocomplete="off" />
      </div>
      <div class="field"><label>显示昵称</label>
        <input id="display_name" autocomplete="off" placeholder="可选" />
      </div>
      <div class="field"><label>协议端类型</label>
        <select id="protocol_backend" class="shell-pretty-select">
          <option value="napcat">NapCat（默认）</option>
          <option value="snowluma">SnowLuma</option>
        </select>
      </div>
      <div class="field"><label>内置 WebUI 端口（可选）</label>
        <input id="webui_port" type="number" placeholder="留空则自动分配" />
      </div>
      <div class="field" id="rowNewWebuiToken"><label>内置 WebUI token（可选）</label>
        <input id="webui_token" type="password" autocomplete="off" placeholder="留空则随机生成" />
      </div>
      <hr style="border:none;border-top:1px solid var(--bd);margin:6px 0 14px" />
      <h4 style="margin:0 0 12px;font-size:0.9rem;color:var(--muted);font-weight:700">WS 连接（协议端 → Bot，可选）</h4>
      <p class="muted" style="margin:0 0 12px">正向 WS：协议端主动连接 Bot。跨机部署时填写 Bot 地址；留空则按环境变量自动解析（示例：ws://127.0.0.1:8088/onebot/v11/ws）。</p>
      <div class="field"><label>WS 连接地址</label>
        <input id="ws_url" placeholder="ws://bot-host:8088/onebot/v11/ws" autocomplete="off" />
      </div>
      <div class="field"><label>连接名（协议端侧显示）</label>
        <input id="ws_name" placeholder="pallas" autocomplete="off" />
      </div>
      <div class="field"><label>WS Token（与 Bot 侧 access_token 一致）</label>
        <input id="ws_token" type="password" autocomplete="off" placeholder="留空则不鉴权" />
      </div>
      <div class="row" style="margin-top:4px">
        <button class="btn" type="button" onclick="createAccount()">创建</button>
      </div>
    </div>
    </div>
{shell_close}
  <script>
    const basePath = {p};
{token_sync_js}
{common_api_js}
    initPallasShellThemeFromStorage();
    function applyNewAccountWebuiTokenRow() {{
      const isSl = (document.getElementById("protocol_backend").value || "napcat").trim().toLowerCase() === "snowluma";
      const row = document.getElementById("rowNewWebuiToken");
      if (row) row.style.display = isSl ? "none" : "";
    }}
    document.getElementById("protocol_backend").addEventListener("change", applyNewAccountWebuiTokenRow);
    applyNewAccountWebuiTokenRow();
    async function createAccount() {{
      try {{
        const wport = document.getElementById("webui_port").value.trim();
        const pb = (document.getElementById("protocol_backend").value || "napcat").trim().toLowerCase();
        const wtok = pb === "snowluma" ? "" : document.getElementById("webui_token").value.trim();
        const wn = parseInt(wport, 10);
        const disp = document.getElementById("display_name").value.trim();
        const qq = document.getElementById("qq").value.trim();
        const wsUrl = document.getElementById("ws_url").value.trim();
        const wsName = document.getElementById("ws_name").value.trim();
        const wsTok = document.getElementById("ws_token").value;
        const body = {{
          id: qq,
          qq,
          display_name: disp,
          enabled: true,
          protocol_backend: pb === "snowluma" ? "snowluma" : "napcat",
          ...(wport && !Number.isNaN(wn) ? {{ webui_port: wn }} : {{}}),
          ...(wtok ? {{ webui_token: wtok }} : {{}}),
          ...(wsUrl ? {{ ws_url: wsUrl }} : {{}}),
          ...(wsName ? {{ ws_name: wsName }} : {{}}),
          ...(wsTok ? {{ ws_token: wsTok }} : {{}}),
        }};
        if (!qq) throw new Error("请填写 QQ 号");
        await api("/api/accounts", {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify(body) }});
        const t = (document.getElementById("token").value || "").trim();
        location.href = basePath;
      }} catch (e) {{ alert(e.message); }}
    }}
  </script>
</body>
</html>
"""


def render_protocol_assets_page(base_path: str, pallas_console_http_base: str = "/pallas") -> str:
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    common_api_js = _render_common_api_js()
    token_sync_js = _render_hidden_token_sync_js("backDash")
    shell_open = render_protocol_shell_open(
        path, pallas_console_http_base, active="assets", page_title="协议资产", page_desc="运行时下载与 Docker"
    )
    shell_close = render_protocol_shell_close(path, active="assets", pallas_console_http_base=pallas_console_http_base)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
{shell_head_assets(path)}  <title>协议资产 · 协议端</title>
</head>
<body>
  <input type="hidden" id="token" value="" autocomplete="off" />
  {shell_open}
    <div class="card">
      <p class="muted" style="margin:0 0 14px">
        在此管理 NapCat / SnowLuma 发行包与全局运行方式；改完后点上方「保存设置」。
      </p>
      <div class="row" style="gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px">
        <button class="btn secondary" type="button" id="btnCleanupDist" onclick="cleanupRuntimeDistCaches()">清理下载缓存</button>
        <span style="flex:1"></span>
        <span id="saveProfileDirtyHint" class="muted" style="display:none;color:#b91c1c;font-weight:600">有未保存修改</span>
        <button class="btn" id="btnSaveProfile" type="button" onclick="saveUnifiedRuntimeProfile()" style="font-size:0.92rem;padding:10px 18px;font-weight:700">保存设置</button>
      </div>
      <div style="margin:4px 0 14px;padding:14px 16px;border:1px solid var(--bd);border-radius:var(--radius-lg);background:var(--bg1)">
        <div class="row" style="align-items:center;gap:10px;flex-wrap:wrap">
          <input id="followBotLifecycle" type="checkbox" style="width:auto;height:auto;accent-color:var(--accent)" />
          <label for="followBotLifecycle" class="muted" style="margin:0;font-size:0.9rem;line-height:1.45">
            实例随 Bot 启停（全局）
          </label>
        </div>
      </div>
      <div class="assets-napcat-global-card" style="margin:0 0 16px;border:1px solid var(--bd);border-radius:var(--radius);padding:16px 18px;background:var(--bg1)">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px">
          <span style="font-size:0.95rem;font-weight:700;color:var(--txt)">全局运行模式</span>
        </div>
        <div class="row" style="gap:12px;align-items:flex-end;flex-wrap:wrap">
          <div class="field" style="margin:0;min-width:170px;flex:1">
            <label>NapCat 运行模式</label>
            <select id="runtimeModeNapcat" class="shell-pretty-select" onchange="onRuntimeModeChanged()">
              <option value="docker">Docker</option>
              <option value="appimage">AppImage</option>
              <option value="shell">Shell</option>
            </select>
          </div>
          <div class="field" style="margin:0;min-width:170px;flex:1">
            <label>SnowLuma 运行模式</label>
            <select id="runtimeModeSnowluma" class="shell-pretty-select" onchange="onRuntimeModeChanged()">
              <option value="docker">Docker</option>
              <option value="appimage">AppImage</option>
              <option value="shell">Shell</option>
            </select>
          </div>
          <div class="field" style="margin:0;min-width:190px;flex:1">
            <label>下载目标平台（NapCat）</label>
            <select id="targetPlatform" class="shell-pretty-select">
              <option value="auto">auto（跟随当前平台）</option>
              <option value="linux-amd64">linux-amd64</option>
              <option value="linux-arm64">linux-arm64</option>
              <option value="windows-amd64">windows-amd64</option>
            </select>
          </div>
        </div>
        <div class="row" style="gap:12px;align-items:flex-end;margin-top:10px">
          <div class="field" style="margin:0;min-width:260px;flex:1;max-width:520px">
            <label>保存全局运行配置时：对协议 Docker 容器的处理</label>
            <select id="runtimeProfilePruneContainers" class="shell-pretty-select">
              <option value="all">NapCat 与 SnowLuma 全部</option>
              <option value="napcat">仅 NapCat</option>
              <option value="snowluma">仅 SnowLuma</option>
            </select>
          </div>
        </div>
        <p class="muted" style="margin:8px 0 0;font-size:0.82rem;line-height:1.45">
          点击本页「保存设置」并写入全局运行模式或镜像后，会按此处范围<strong>先停止</strong>对应协议账号进程，再<strong>删除已有 Docker 容器</strong>，避免旧容器继续占用旧镜像或端口。
          只更新一侧镜像时可点「仅 NapCat / 仅 SnowLuma」；<strong>同一端</strong>在 Docker 与 AppImage/Shell 之间切换时须选对应该端的清理范围（或「全部」），否则无法一步清掉该端旧容器。
        </p>
        <div id="dockerProfileArea" style="margin-top:10px;display:none">
          <div class="row" style="gap:8px;align-items:flex-end">
            <div class="field" style="margin:0;min-width:260px;flex:1">
              <label>NapCat Docker 镜像</label>
              <input id="dockerImage" placeholder="mlikiowa/napcat-docker:latest" autocomplete="off" />
            </div>
            <button class="btn secondary" id="btnPullImage" type="button" onclick="pullDockerImage()">拉取镜像</button>
            <button class="btn secondary" id="btnListImage" type="button" onclick="listDockerImages('napcat')">查看本地镜像</button>
          </div>
          <div class="row" style="gap:8px;align-items:flex-end;margin-top:8px">
            <div class="field" style="margin:0;min-width:260px;flex:1">
              <label>SnowLuma Docker 镜像</label>
              <input id="snowlumaDockerImage" placeholder="motricseven7/snowluma:latest" autocomplete="off" />
            </div>
            <button class="btn secondary" id="btnPullSnowlumaImage" type="button" onclick="pullSnowlumaDockerImage()">拉取镜像</button>
            <button class="btn secondary" id="btnListSnowlumaImage" type="button" onclick="listDockerImages('snowluma')">查看本地镜像</button>
          </div>
          <div class="row" style="gap:8px;align-items:flex-end;margin-top:8px;flex-wrap:wrap">
            <div class="field" style="margin:0;min-width:220px;flex:1">
              <label>NapCat 本地镜像</label>
              <select id="dockerImageSelect" class="shell-pretty-select">
                <option value="">（先点 NapCat「查看本地镜像」，仅当前配置的仓库）</option>
              </select>
            </div>
            <button class="btn secondary" id="btnUseSelectedImage" type="button" onclick="applySelectedDockerImage()">填入 NapCat 镜像框</button>
            <div class="field" style="margin:0;min-width:220px;flex:1">
              <label>SnowLuma 本地镜像</label>
              <select id="snowlumaDockerImageSelect" class="shell-pretty-select">
                <option value="">（先点 SnowLuma「查看本地镜像」，仅当前配置的仓库）</option>
              </select>
            </div>
            <button class="btn secondary" id="btnUseSelectedSnowlumaImage" type="button" onclick="applySelectedSnowlumaDockerImage()">填入 SnowLuma 镜像框</button>
          </div>
          <div class="row" style="gap:8px;align-items:flex-end;margin-top:8px;flex-wrap:wrap">
            <button class="btn secondary" id="btnStopAllDocker" type="button" onclick="stopAllDockerContainers()">停止全部协议容器</button>
            <button class="btn secondary" id="btnPruneStoppedDocker" type="button" onclick="pruneStoppedDockerContainers()">清理已停止协议容器</button>
          </div>
          <p class="muted" style="margin:8px 0 0;font-size:0.82rem">Docker 模式需本机已安装 Docker；镜像名见上。</p>
          <details style="margin-top:10px">
            <summary class="muted" style="cursor:pointer">查看 Docker pull 日志</summary>
            <pre class="mono" id="dockerPullLogs" style="max-height:min(42vh,360px);overflow:auto;margin-top:8px;font-size:12px;background:#0f1624;color:#dbe7ff;padding:10px;border-radius:10px;border:1px solid var(--bd)">尚未执行拉取。</pre>
          </details>
        </div>
      </div>
      <div class="proto-switch-toolbar">
        <div class="row" style="gap:10px;align-items:flex-end;flex-wrap:wrap">
          <div class="field" style="margin:0;min-width:200px">
            <label for="assetsProtoSelect">发行包</label>
            <select id="assetsProtoSelect" class="shell-pretty-select" aria-label="协议发行包类型">
              <option value="napcat">NapCat</option>
              <option value="snowluma">SnowLuma</option>
            </select>
          </div>
        </div>
      </div>
      <div id="assetsPaneUnified">
      <h2 id="assetsProtoHeading" class="section-title" style="margin:16px 0 8px;font-size:1.05rem;font-weight:700">发行包</h2>
      <p id="assetsProtoHint" class="muted" style="margin:0 0 10px;font-size:0.86rem">在 NapCat 与 SnowLuma 间切换；全局运行模式与 Docker 镜像见上方。</p>
      <div id="rowAssetsSlTargetPlatform" class="field" style="margin-bottom:12px;display:none">
        <label>下载目标平台（SnowLuma）</label>
        <select id="slTargetPlatform" class="shell-pretty-select">
          <option value="auto">自动（按本机系统）</option>
          <option value="windows-amd64">windows-amd64</option>
          <option value="linux-amd64">linux-amd64</option>
          <option value="linux-arm64">linux-arm64</option>
        </select>
      </div>
      <div class="kpi-grid">
        <div class="kpi"><div class="k">任务状态</div><div class="v" id="rtStatus">-</div></div>
        <div class="kpi"><div class="k">当前阶段</div><div class="v" id="rtStage">-</div></div>
        <div class="kpi"><div class="k">目标 / 版本</div><div class="v" id="rtAsset" title="">-</div></div>
        <div class="kpi"><div class="k">最后刷新</div><div class="v" id="rtTime">-</div></div>
      </div>
      <div class="card" style="margin:10px 0 0;box-shadow:none">
        <div class="field" style="margin-bottom:10px">
          <label>状态消息</label>
          <div class="mono" id="rtMessage">-</div>
        </div>
        <div class="field" style="margin-bottom:10px">
          <label>下载来源</label>
          <div class="mono" id="rtSource">-</div>
        </div>
        <div class="field" style="margin-bottom:0">
          <label id="lblRtProgramDir">运行目录</label>
          <div class="mono" id="rtProgramDir">-</div>
        </div>
      </div>
      <div class="row" style="margin-top:12px;flex-wrap:wrap;gap:8px">
        <button class="btn" id="btnAssetDownload" type="button" onclick="assetDownloadRuntime()">立即更新</button>
        <button class="btn secondary" id="btnRescan" type="button" onclick="rescanRuntime()">刷新检测</button>
        <button class="btn secondary" id="btnAssetRefresh" type="button" onclick="assetRefreshOverview()">刷新状态</button>
      </div>
      <div style="margin-top:18px;border:1px solid var(--bd);border-radius:var(--radius);padding:16px 18px;background:var(--bg1)">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px">
          <span style="font-size:0.95rem;font-weight:700;color:var(--txt)">选择版本</span>
          <button class="btn secondary" id="btnLoadReleases" type="button" onclick="loadAssetReleases()" style="font-size:0.82rem;padding:7px 14px">加载版本列表</button>
        </div>
        <div id="releasesArea" style="display:none">
          <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px">
            <select id="releaseSelect" class="shell-pretty-select" style="flex:1;min-width:200px;height:40px"></select>
            <button class="btn secondary" id="btnDownloadTag" type="button" onclick="assetActivateSelectedTag()">选择此版本</button>
          </div>
          <div id="releaseDetail" class="muted" style="font-size:0.78rem;min-height:1.4em"></div>
        </div>
        <p id="releasesPlaceholder" class="muted" style="margin:0;font-size:0.82rem">先点「加载版本列表」。</p>
      </div>
      <div style="margin-top:18px;border:1px solid var(--bd);border-radius:var(--radius);padding:16px 18px;background:var(--bg1)">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:10px">
          <span style="font-size:0.95rem;font-weight:700;color:var(--txt)">本机解压目录（切换托管版本）</span>
          <button class="btn secondary" type="button" id="btnAssetInvRefresh" onclick="loadAssetLocalInventory()">刷新列表</button>
        </div>
        <p class="muted" style="margin:0 0 10px;font-size:0.82rem">按 Release 标签分子目录；切换后使用对应托管的账号需重启协议进程。</p>
        <p id="assetDistFilesHint" class="muted" style="font-size:0.78rem;margin:0 0 8px"></p>
        <div id="assetLocalInvPlaceholder" class="muted" style="font-size:0.82rem">点击「刷新列表」加载。</div>
        <div id="assetLocalInvTable" style="display:none;margin-top:8px;overflow:auto;border:1px solid var(--bd);border-radius:var(--radius-sm);max-height:min(36vh,320px)">
          <table class="acc-table" style="width:100%;border-collapse:collapse;font-size:0.84rem">
            <thead><tr>
              <th style="text-align:left;padding:8px">版本（目录）</th>
              <th style="text-align:left;padding:8px">修改时间</th>
              <th style="text-align:left;padding:8px">托管</th>
              <th style="text-align:right;padding:8px">操作</th>
            </tr></thead>
            <tbody id="assetLocalInvBody"></tbody>
          </table>
        </div>
      </div>
      <details style="margin-top:14px">
        <summary id="assetsRuntimeJsonSummary" class="muted" style="cursor:pointer">状态 JSON</summary>
        <pre class="mono muted" id="runtimeStatus" tabindex="0" title="框选复制；聚焦时暂停自动刷新" style="max-height:min(70vh,720px);overflow:auto;margin-top:8px;font-size:12px"></pre>
      </details>
      </div>
    </div>
{shell_close}
  <script>
    const basePath = {p};
{common_api_js}
    initPallasShellThemeFromStorage();
    let runtimeRefreshing = false;
    let runtimeProfileSnapshot = null;
    let runtimeProfileWatchBound = false;
    let pendingTag = null;
    let pendingSnowlumaTag = null;
    let _assetReleaseList = [];
    function assetsProtoIsSl() {{
      const s = document.getElementById("assetsProtoSelect");
      return !!(s && String(s.value || "").toLowerCase() === "snowluma");
    }}
    async function assetRefreshOverview(opts = {{}}) {{
      if (assetsProtoIsSl()) return await refreshSnowlumaOverview(opts);
      return await refreshRuntime(opts);
    }}
    function assetDownloadRuntime() {{
      void (assetsProtoIsSl() ? downloadSnowlumaRuntime() : downloadRuntime());
    }}
    function anyRuntimeDocker() {{
      const a = String(document.getElementById("runtimeModeNapcat")?.value || "");
      const b = String(document.getElementById("runtimeModeSnowluma")?.value || "");
      return a === "docker" || b === "docker";
    }}
    function syncAssetDownloadButtonText() {{
      const isDocker = anyRuntimeDocker();
      const dlBtn = document.getElementById("btnAssetDownload");
      if (!dlBtn) return;
      if (assetsProtoIsSl()) {{
        dlBtn.textContent = "下载 / 更新";
      }} else {{
        dlBtn.textContent = isDocker ? "Docker 模式无需下载" : "立即更新";
      }}
    }}
    function syncSelectVersionButtonState() {{
      const dlTagBtn = document.getElementById("btnDownloadTag");
      if (!dlTagBtn) return;
      const napDocker = String(document.getElementById("runtimeModeNapcat")?.value || "") === "docker";
      const slDocker = String(document.getElementById("runtimeModeSnowluma")?.value || "") === "docker";
      const sl = assetsProtoIsSl();
      const disable = sl ? slDocker : napDocker;
      dlTagBtn.disabled = disable;
      dlTagBtn.title = disable
        ? (sl ? "SnowLuma 为 Docker 模式时无需选择本地发行包版本。" : "NapCat 为 Docker 模式时无需选择本地发行包版本。")
        : "";
    }}
    function setAssetsProtocolPane(which, pushUrl) {{
      const sel = document.getElementById("assetsProtoSelect");
      const v = (String(which || "napcat").toLowerCase() === "snowluma") ? "snowluma" : "napcat";
      if (sel) sel.value = v;
      const slRow = document.getElementById("rowAssetsSlTargetPlatform");
      if (slRow) slRow.style.display = v === "snowluma" ? "block" : "none";
      const rs = document.getElementById("btnRescan");
      if (rs) rs.style.display = v === "snowluma" ? "none" : "";
      const h = document.getElementById("assetsProtoHeading");
      if (h) h.textContent = v === "snowluma" ? "SnowLuma 发行包" : "NapCat 发行包";
      const hi = document.getElementById("assetsProtoHint");
      if (hi) {{
        hi.textContent = v === "snowluma"
          ? "从 GitHub Release 下载；Docker 见上方「SnowLuma Docker 镜像」与「拉取镜像」。"
          : "从官方渠道下载；Docker 见上方「NapCat Docker 镜像」与「拉取镜像」。";
      }}
      const lb = document.getElementById("lblRtProgramDir");
      if (lb) lb.textContent = v === "snowluma" ? "程序根目录（index.mjs）" : "运行目录";
      const rf = document.getElementById("btnAssetRefresh");
      if (rf) rf.textContent = "刷新状态";
      const sm = document.getElementById("assetsRuntimeJsonSummary");
      if (sm) sm.textContent = v === "snowluma" ? "SnowLuma 状态 JSON" : "NapCat 状态 JSON";
      try {{
        localStorage.setItem("pallas_protocol_assets_pane", v);
      }} catch (e) {{}}
      if (pushUrl !== false) {{
        const u = new URL(location.href);
        u.searchParams.set("protocol", v);
        history.replaceState(null, "", u.pathname + u.search);
      }}
      syncAssetsSaveButton();
      syncAssetDownloadButtonText();
      syncSelectVersionButtonState();
      const ra = document.getElementById("releasesArea");
      const rp = document.getElementById("releasesPlaceholder");
      const rsel = document.getElementById("releaseSelect");
      if (ra) ra.style.display = "none";
      if (rp) rp.style.display = "block";
      if (rsel) rsel.innerHTML = "";
      _assetReleaseList = [];
      if (v === "snowluma") {{
        const slTpEl = document.getElementById("slTargetPlatform");
        if (slTpEl) {{
          const sv = localStorage.getItem("pallas_protocol_sl_target_platform") || "";
          if (["auto", "windows-amd64", "linux-amd64", "linux-arm64"].includes(sv)) slTpEl.value = sv;
          if (typeof shellPrettySyncSelect === "function") shellPrettySyncSelect(slTpEl);
        }}
      }}
      if (typeof shellPrettySyncSelect === "function" && sel) shellPrettySyncSelect(sel);
      void loadAssetLocalInventory();
    }}
    function initAssetsProtocolPane() {{
      const u = new URL(location.href);
      let p = (u.searchParams.get("protocol") || localStorage.getItem("pallas_protocol_assets_pane") || "napcat").toLowerCase();
      if (p !== "snowluma") p = "napcat";
      setAssetsProtocolPane(p, false);
      const slTp = document.getElementById("slTargetPlatform");
      if (slTp) {{
        const sv = localStorage.getItem("pallas_protocol_sl_target_platform") || "";
        if (["auto", "windows-amd64", "linux-amd64", "linux-arm64"].includes(sv)) slTp.value = sv;
      }}
    }}
    const _assetsProtoSel = document.getElementById("assetsProtoSelect");
    if (_assetsProtoSel) {{
      _assetsProtoSel.addEventListener("change", () => setAssetsProtocolPane(_assetsProtoSel.value));
    }}
    initAssetsProtocolPane();
    const _slTpCh = document.getElementById("slTargetPlatform");
    if (_slTpCh) {{
      _slTpCh.addEventListener("change", () => {{
        try {{ localStorage.setItem("pallas_protocol_sl_target_platform", _slTpCh.value || "auto"); }} catch (e) {{}}
      }});
    }}
    function setBtnBusy(el, busy, idleText, busyText) {{
      if (!el) return;
      el.disabled = !!busy;
      el.textContent = busy ? busyText : idleText;
      el.classList.toggle("busy", !!busy);
    }}
    async function cleanupRuntimeDistCaches() {{
      if (!confirm("删除已下载的安装包（runtime_dist），不删解压目录与 manifest。确定？")) return;
      const btn = document.getElementById("btnCleanupDist");
      setBtnBusy(btn, true, "清理下载缓存", "清理中...");
      try {{
        const r = await api("/api/runtime/cleanup-dist", {{ method: "POST" }});
        const nc = r.napcat_files_removed ?? 0;
        const sl = r.snowluma_files_removed ?? 0;
        alert("已清理：NapCat " + nc + " 个文件，SnowLuma " + sl + " 个文件。");
      }} catch (e) {{
        alert(e.message || e);
      }} finally {{
        setBtnBusy(btn, false, "清理下载缓存", "清理中...");
      }}
      void loadAssetLocalInventory();
    }}
    function invEsc(t) {{
      return String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }}
    async function loadAssetLocalInventory() {{
      const ph = document.getElementById("assetLocalInvPlaceholder");
      const tb = document.getElementById("assetLocalInvTable");
      const body = document.getElementById("assetLocalInvBody");
      const distEl = document.getElementById("assetDistFilesHint");
      if (!ph || !tb || !body) return;
      ph.style.display = "block";
      ph.textContent = "加载中…";
      const sl = assetsProtoIsSl();
      const ep = sl ? "/api/snowluma/runtime/local-inventory" : "/api/runtime/local-inventory";
      try {{
        const data = await api(ep);
        const dirs = Array.isArray(data.extract_dirs) ? data.extract_dirs : [];
        const files = Array.isArray(data.dist_files) ? data.dist_files : [];
        if (distEl) {{
          distEl.textContent = files.length
            ? ("runtime_dist 中现有文件（" + files.length + "）：" + files.map((f) => f.name).join(" · "))
            : "runtime_dist 目录暂无文件。";
        }}
        if (!dirs.length) {{
          ph.textContent = "暂无解压子目录（成功安装至少一次后会出现对应 Release 标签目录）。";
          tb.style.display = "none";
          body.innerHTML = "";
          return;
        }}
        ph.style.display = "none";
        tb.style.display = "block";
        body.innerHTML = dirs.map((d) => {{
          const active = !!d.is_active;
          const mt = d.mtime_iso ? new Date(d.mtime_iso).toLocaleString("zh-CN") : "-";
          const btn = active
            ? '<span class="muted">当前托管</span>'
            : (sl
              ? ("<button type=\\"button\\" class=\\"btn secondary\\" onclick='activateSnowlumaExtract(" + JSON.stringify(d.name) + ")'>托管使用此目录</button>")
              : ("<button type=\\"button\\" class=\\"btn secondary\\" onclick='activateNapcatExtract(" + JSON.stringify(d.name) + ")'>托管使用此目录</button>"));
          return "<tr><td style=\\"padding:8px;font-family:var(--font-mono,monospace);font-size:0.8rem\\">" + invEsc(d.name) + "</td>"
            + "<td style=\\"padding:8px\\">" + invEsc(mt) + "</td>"
            + "<td style=\\"padding:8px\\">" + (active ? "当前" : "—") + "</td>"
            + "<td style=\\"padding:8px;text-align:right\\">" + btn + "</td></tr>";
        }}).join("");
      }} catch (e) {{
        ph.textContent = "加载失败：" + (e.message || e);
        tb.style.display = "none";
      }}
    }}
    async function activateNapcatExtract(folderName) {{
      if (!folderName) return;
      if (!confirm("将当前托管的 NapCat 切换到解压版本：\\n" + folderName + "\\n（不重新下载）")) return;
      try {{
        await api("/api/runtime/activate-tag", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ tag: folderName }}),
        }});
        await refreshRuntime({{ silent: true }});
        await loadAssetLocalInventory();
        alert("已切换托管目录。使用此托管的账号请重启协议端进程后生效。");
      }} catch (e) {{
        alert(e.message || e);
      }}
    }}
    async function activateSnowlumaExtract(folderName) {{
      if (!folderName) return;
      if (!confirm("将当前托管的 SnowLuma 切换到解压版本：\\n" + folderName + "\\n（不重新下载）")) return;
      try {{
        await api("/api/snowluma/runtime/activate-tag", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ tag: folderName }}),
        }});
        const slo = await api("/api/snowluma/runtime/overview");
        fillRuntimeOverviewFromPayload(slo);
        await loadAssetLocalInventory();
        alert("已切换托管目录。使用此托管的账号请重启协议端进程后生效。");
      }} catch (e) {{
        alert(e.message || e);
      }}
    }}
    function statusText(s) {{
      if (!s) return "未知";
      const map = {{
        idle: "空闲",
        downloading: "下载中",
        extracting: "处理中",
        installing: "安装中",
        done: "完成",
        error: "失败",
      }};
      return map[s] || s;
    }}
    function stageText(msg) {{
      const m = String(msg || "");
      if (!m) return "-";
      if (m.includes("下载")) return "下载";
      if (m.includes("解压") || m.includes("安装")) return "安装/解包";
      if (m.includes("检测")) return "检测";
      if (m.includes("完成")) return "完成";
      if (m.includes("失败") || m.includes("错误")) return "失败";
      return "处理中";
    }}
    function setText(id, value) {{
      const el = document.getElementById(id);
      if (!el) return;
      const v = String(value || "-");
      el.textContent = v;
      el.title = v;
    }}
    function appendDockerPullLog(line) {{
      const el = document.getElementById("dockerPullLogs");
      if (!el) return;
      const now = new Date().toLocaleTimeString();
      const text = `[${{now}}] ${{String(line || "")}}`;
      if (!el.textContent || el.textContent === "尚未执行拉取。") {{
        el.textContent = text;
      }} else {{
        el.textContent += "\\n" + text;
      }}
      el.scrollTop = el.scrollHeight;
    }}
    function normalizeRuntimeProfile(p) {{
      const leg = ["docker", "appimage", "shell"].includes(String(p.runtime_mode || "")) ? String(p.runtime_mode) : "shell";
      const nap = ["docker", "appimage", "shell"].includes(String(p.napcat_runtime_mode || ""))
        ? String(p.napcat_runtime_mode)
        : leg;
      const snow = ["docker", "appimage", "shell"].includes(String(p.snowluma_runtime_mode || ""))
        ? String(p.snowluma_runtime_mode)
        : leg;
      const platform = ["auto", "linux-amd64", "linux-arm64", "windows-amd64"].includes(String(p.target_platform || ""))
        ? String(p.target_platform)
        : "auto";
      const pr = String(p.prune_containers || "all").toLowerCase();
      const pruneOk = pr === "napcat" || pr === "snowluma" ? pr : "all";
      return {{
        runtime_mode: nap,
        napcat_runtime_mode: nap,
        snowluma_runtime_mode: snow,
        target_platform: platform,
        docker_image: String(p.docker_image || "").trim(),
        snowluma_docker_image: String(p.snowluma_docker_image || "").trim(),
        follow_bot_lifecycle: !!p.follow_bot_lifecycle,
        prune_containers: pruneOk,
      }};
    }}
    function currentRuntimeProfileForm() {{
      return normalizeRuntimeProfile({{
        napcat_runtime_mode: document.getElementById("runtimeModeNapcat")?.value || "shell",
        snowluma_runtime_mode: document.getElementById("runtimeModeSnowluma")?.value || "shell",
        target_platform: document.getElementById("targetPlatform")?.value || "auto",
        docker_image: document.getElementById("dockerImage")?.value || "",
        snowluma_docker_image: document.getElementById("snowlumaDockerImage")?.value || "",
        follow_bot_lifecycle: !!document.getElementById("followBotLifecycle")?.checked,
        prune_containers: (document.getElementById("runtimeProfilePruneContainers")?.value || "all"),
      }});
    }}
    function updateSaveProfileDirtyState() {{
      const hint = document.getElementById("saveProfileDirtyHint");
      if (!hint || !runtimeProfileSnapshot) return;
      const dirty = JSON.stringify(currentRuntimeProfileForm()) !== JSON.stringify(runtimeProfileSnapshot);
      hint.style.display = dirty ? "inline" : "none";
    }}
    function syncAssetsSaveButton() {{
      const btn = document.getElementById("btnSaveProfile");
      if (btn) {{
        btn.disabled = false;
        btn.title = "";
      }}
      const hint = document.getElementById("saveProfileDirtyHint");
      if (hint) {{
        updateSaveProfileDirtyState();
      }}
    }}
    function bindRuntimeProfileWatchers() {{
      if (runtimeProfileWatchBound) return;
      runtimeProfileWatchBound = true;
      ["runtimeModeNapcat", "runtimeModeSnowluma", "targetPlatform", "dockerImage", "snowlumaDockerImage", "followBotLifecycle", "runtimeProfilePruneContainers"].forEach((id) => {{
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener("change", updateSaveProfileDirtyState);
        el.addEventListener("input", updateSaveProfileDirtyState);
      }});
    }}
    function onRuntimeModeChanged() {{
      const isDocker = anyRuntimeDocker();
      const napDocker = String(document.getElementById("runtimeModeNapcat")?.value || "") === "docker";
      const dockerArea = document.getElementById("dockerProfileArea");
      if (dockerArea) dockerArea.style.display = isDocker ? "block" : "none";
      const target = document.getElementById("targetPlatform");
      if (target) target.disabled = napDocker;
      syncSelectVersionButtonState();
      syncAssetDownloadButtonText();
      if (typeof shellPrettySyncSelect === "function") {{
        const r1 = document.getElementById("runtimeModeNapcat");
        const r2 = document.getElementById("runtimeModeSnowluma");
        const tp = document.getElementById("targetPlatform");
        if (r1) shellPrettySyncSelect(r1);
        if (r2) shellPrettySyncSelect(r2);
        if (tp) shellPrettySyncSelect(tp);
      }}
    }}
    async function loadRuntimeProfile() {{
      const data = await api("/api/runtime/profile");
      const p = data.profile || {{}};
      const leg = ["docker", "appimage", "shell"].includes(String(p.runtime_mode || "")) ? p.runtime_mode : "shell";
      const nap = ["docker", "appimage", "shell"].includes(String(p.napcat_runtime_mode || ""))
        ? p.napcat_runtime_mode
        : leg;
      const snow = ["docker", "appimage", "shell"].includes(String(p.snowluma_runtime_mode || ""))
        ? p.snowluma_runtime_mode
        : leg;
      const platform = ["auto", "linux-amd64", "linux-arm64", "windows-amd64"].includes(String(p.target_platform || ""))
        ? p.target_platform
        : "auto";
      document.getElementById("runtimeModeNapcat").value = nap;
      document.getElementById("runtimeModeSnowluma").value = snow;
      document.getElementById("targetPlatform").value = platform;
      document.getElementById("dockerImage").value = String(p.docker_image || "");
      const sld = document.getElementById("snowlumaDockerImage");
      if (sld) sld.value = String(p.snowluma_docker_image || "");
      document.getElementById("followBotLifecycle").checked = !!p.follow_bot_lifecycle;
      const pc = document.getElementById("runtimeProfilePruneContainers");
      if (pc) pc.value = "all";
      runtimeProfileSnapshot = normalizeRuntimeProfile({{ ...p, prune_containers: "all" }});
      bindRuntimeProfileWatchers();
      updateSaveProfileDirtyState();
      onRuntimeModeChanged();
      if (typeof shellPrettySyncSelect === "function") {{
        ["runtimeModeNapcat", "runtimeModeSnowluma", "targetPlatform", "dockerImageSelect", "snowlumaDockerImageSelect", "runtimeProfilePruneContainers", "assetsProtoSelect"].forEach((id) => {{
          const el = document.getElementById(id);
          if (el) shellPrettySyncSelect(el);
        }});
      }}
    }}
    async function saveUnifiedRuntimeProfile() {{
      await saveRuntimeProfile();
    }}
    async function saveRuntimeProfile() {{
      const btn = document.getElementById("btnSaveProfile");
      setBtnBusy(btn, true, "保存设置", "保存中...");
      try {{
        const body = {{
          napcat_runtime_mode: document.getElementById("runtimeModeNapcat").value,
          snowluma_runtime_mode: document.getElementById("runtimeModeSnowluma").value,
          target_platform: document.getElementById("targetPlatform").value,
          docker_image: document.getElementById("dockerImage").value.trim(),
          snowluma_docker_image: (document.getElementById("snowlumaDockerImage")?.value || "").trim(),
          follow_bot_lifecycle: !!document.getElementById("followBotLifecycle").checked,
          prune_containers: (document.getElementById("runtimeProfilePruneContainers")?.value || "all"),
        }};
        await api("/api/runtime/profile", {{
          method: "PUT",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(body),
        }});
        runtimeProfileSnapshot = normalizeRuntimeProfile(body);
        updateSaveProfileDirtyState();
        await assetRefreshOverview({{ silent: true }});
      }} catch (e) {{
        alert(e.message || e);
      }} finally {{
        setBtnBusy(btn, false, "保存设置", "保存中...");
      }}
    }}
    async function pullSnowlumaDockerImage() {{
      const btn = document.getElementById("btnPullSnowlumaImage");
      setBtnBusy(btn, true, "拉取镜像", "拉取中...");
      try {{
        const image = (document.getElementById("snowlumaDockerImage")?.value || "").trim();
        appendDockerPullLog("开始拉取 SnowLuma 镜像: " + (image || "motricseven7/snowluma:latest"));
        const body = {{ image }};
        const res = await api("/api/runtime/docker/pull", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(body),
        }});
        const output = String(res.output || "").trim();
        if (output) appendDockerPullLog(output);
        if (!res.ok) {{
          appendDockerPullLog("拉取失败，退出码: " + String(res.code ?? "-"));
          return;
        }}
        appendDockerPullLog("拉取成功: " + String(res.image || ""));
      }} catch (e) {{
        appendDockerPullLog("拉取异常: " + String(e.message || e));
      }} finally {{
        setBtnBusy(btn, false, "拉取镜像", "拉取中...");
      }}
    }}
    async function pullDockerImage() {{
      const btn = document.getElementById("btnPullImage");
      setBtnBusy(btn, true, "拉取镜像", "拉取中...");
      try {{
        const image = document.getElementById("dockerImage").value.trim();
        appendDockerPullLog("开始拉取 NapCat 镜像: " + (image || "mlikiowa/napcat-docker:latest"));
        const body = {{ image }};
        const res = await api("/api/runtime/docker/pull", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(body),
        }});
        const output = String(res.output || "").trim();
        if (output) appendDockerPullLog(output);
        if (!res.ok) {{
          appendDockerPullLog("拉取失败，退出码: " + String(res.code ?? "-"));
          return;
        }}
        appendDockerPullLog("拉取成功: " + String(res.image || ""));
      }} catch (e) {{
        appendDockerPullLog("拉取异常: " + String(e.message || e));
      }} finally {{
        setBtnBusy(btn, false, "拉取镜像", "拉取中...");
      }}
    }}
    async function listDockerImages(protocol) {{
      const proto = String(protocol || "napcat").toLowerCase();
      const isSl = proto === "snowluma";
      const btn = document.getElementById(isSl ? "btnListSnowlumaImage" : "btnListImage");
      const label = isSl ? "SnowLuma 查看本地镜像" : "NapCat 查看本地镜像";
      setBtnBusy(btn, true, label, "查询中...");
      try {{
        const res = await api("/api/runtime/docker/images?protocol=" + encodeURIComponent(proto));
        if (!res.ok) {{
          appendDockerPullLog("查询失败: " + String(res.detail || res.output || res.code || "未知错误"));
          return;
        }}
        const fr = res.filter_repository ? String(res.filter_repository) : "";
        if (fr) {{
          appendDockerPullLog((isSl ? "SnowLuma" : "NapCat") + " 按当前配置仓库筛选: " + fr);
        }}
        const images = Array.isArray(res.images) ? res.images : [];
        const sel = document.getElementById(isSl ? "snowlumaDockerImageSelect" : "dockerImageSelect");
        const currentImage = String(
          document.getElementById(isSl ? "snowlumaDockerImage" : "dockerImage")?.value || ""
        ).trim();
        if (sel) {{
          const options = [`<option value="">（请选择）</option>`];
          images.forEach((img) => {{
            const name = String(img.name || "").trim();
            if (!name) return;
            const meta = [img.created_since ? String(img.created_since) : "", img.size ? String(img.size) : ""].filter(Boolean).join(" / ");
            const currentMark = name === currentImage ? "（当前）" : "";
            options.push(`<option value="${{name.replace(/"/g, "&quot;")}}">${{name}}${{currentMark ? " " + currentMark : ""}}${{meta ? " · " + meta : ""}}</option>`);
          }});
          sel.innerHTML = options.join("");
          if (currentImage) sel.value = currentImage;
          if (typeof shellPrettySyncSelect === "function") shellPrettySyncSelect(sel);
        }}
        if (!images.length) {{
          appendDockerPullLog("本地暂无匹配镜像（可检查上方输入框中的镜像名是否与已拉取仓库一致）。");
          return;
        }}
        appendDockerPullLog("本地镜像列表（" + String(images.length) + "）:");
        images.slice(0, 80).forEach((img) => {{
          const line = [
            String(img.name || "<none>:<none>"),
            img.id ? `id=${{img.id}}` : "",
            img.created_since ? `created=${{img.created_since}}` : "",
            img.size ? `size=${{img.size}}` : "",
          ].filter(Boolean).join(" | ");
          appendDockerPullLog("  - " + line);
        }});
      }} catch (e) {{
        appendDockerPullLog("查询异常: " + String(e.message || e));
      }} finally {{
        setBtnBusy(btn, false, label, "查询中...");
      }}
    }}
    function applySelectedDockerImage() {{
      const sel = document.getElementById("dockerImageSelect");
      const input = document.getElementById("dockerImage");
      if (!sel || !input) return;
      const v = String(sel.value || "").trim();
      if (!v) {{
        alert("请先从 NapCat 本地镜像下拉框选择一项。");
        return;
      }}
      input.value = v;
      appendDockerPullLog("已填入 NapCat 镜像: " + v + "（记得点「保存设置」生效）");
    }}
    function applySelectedSnowlumaDockerImage() {{
      const sel = document.getElementById("snowlumaDockerImageSelect");
      const input = document.getElementById("snowlumaDockerImage");
      if (!sel || !input) return;
      const v = String(sel.value || "").trim();
      if (!v) {{
        alert("请先从 SnowLuma 本地镜像下拉框选择一项。");
        return;
      }}
      input.value = v;
      appendDockerPullLog("已填入 SnowLuma 镜像: " + v + "（记得点「保存设置」生效）");
    }}
    async function stopAllDockerContainers() {{
      const btn = document.getElementById("btnStopAllDocker");
      setBtnBusy(btn, true, "停止全部协议容器", "处理中...");
      try {{
        const res = await api("/api/runtime/docker/stop-all", {{ method: "POST" }});
        if (!res.ok) {{
          appendDockerPullLog("批量停止失败: " + String(res.detail || res.output || res.code || "未知错误"));
          return;
        }}
        appendDockerPullLog("已停止协议容器数量: " + String(res.stopped || 0));
        if (res.output) appendDockerPullLog(String(res.output));
      }} catch (e) {{
        appendDockerPullLog("批量停止异常: " + String(e.message || e));
      }} finally {{
        setBtnBusy(btn, false, "停止全部协议容器", "处理中...");
      }}
    }}
    async function pruneStoppedDockerContainers() {{
      const btn = document.getElementById("btnPruneStoppedDocker");
      setBtnBusy(btn, true, "清理已停止协议容器", "处理中...");
      try {{
        const res = await api("/api/runtime/docker/prune-stopped", {{ method: "POST" }});
        if (!res.ok) {{
          appendDockerPullLog("清理失败: " + String(res.detail || res.output || res.code || "未知错误"));
          return;
        }}
        appendDockerPullLog("已清理停止容器数量: " + String(res.removed || 0));
        if (res.output) appendDockerPullLog(String(res.output));
      }} catch (e) {{
        appendDockerPullLog("清理异常: " + String(e.message || e));
      }} finally {{
        setBtnBusy(btn, false, "清理已停止协议容器", "处理中...");
      }}
    }}
    async function refreshRuntime(opts = {{}}) {{
      const silent = !!opts.silent;
      if (runtimeRefreshing) return;
      runtimeRefreshing = true;
      if (!silent) {{
        setBtnBusy(document.getElementById("btnAssetRefresh"), true, "刷新状态", "刷新中...");
      }}
      try {{
        const data = await api("/api/runtime");
        {{
          const rs = document.getElementById("runtimeStatus");
          if (rs && !shouldPauseLiveLogDomWrite(rs)) rs.textContent = JSON.stringify(data, null, 2);
        }}
        const job = data.job || {{}};
        const d = data.download || {{}};
        const manifest = data.manifest || {{}};
        setText("rtStatus", statusText(job.status));
        setText("rtStage", stageText(job.message));
        const tag = pendingTag || job.tag || manifest.release_tag || d.tag || "";
        const assetEl = document.getElementById("rtAsset");
        if (assetEl) {{ assetEl.title = d.asset || manifest.asset_name || ""; }}
        setText("rtAsset", tag || d.asset || manifest.asset_name || "-");
        setText("rtMessage", job.message || "-");
        setText("rtSource", manifest.source_url || `${{d.repo || "-"}} @ ${{tag || "latest"}}`);
        setText("rtProgramDir", data.effective_program_dir || manifest.program_dir || "-");
        setText("rtTime", new Date().toLocaleTimeString());
      }} catch (e) {{
        {{
          const rs = document.getElementById("runtimeStatus");
          if (rs && !shouldPauseLiveLogDomWrite(rs)) rs.textContent = String(e.message || e);
        }}
        setText("rtStatus", "失败");
        setText("rtStage", "错误");
        setText("rtMessage", String(e.message || e));
        setText("rtTime", new Date().toLocaleTimeString());
      }} finally {{
        if (!silent) {{
          setBtnBusy(document.getElementById("btnAssetRefresh"), false, "刷新状态", "刷新中...");
        }}
        runtimeRefreshing = false;
      }}
    }}
    async function refreshSnowlumaOverview(opts = {{}}) {{
      const silent = !!opts.silent;
      if (!silent) {{
        setBtnBusy(document.getElementById("btnAssetRefresh"), true, "刷新状态", "刷新中...");
      }}
      try {{
        const sl = await api("/api/snowluma/runtime/overview");
        fillRuntimeOverviewFromPayload(sl);
      }} catch (e) {{
        {{
          const rs = document.getElementById("runtimeStatus");
          if (rs && !shouldPauseLiveLogDomWrite(rs)) rs.textContent = String(e.message || e);
        }}
        setText("rtStatus", "失败");
        setText("rtStage", "错误");
        setText("rtMessage", String(e.message || e));
        setText("rtTime", new Date().toLocaleTimeString());
        if (!silent) alert(String(e.message || e));
      }} finally {{
        if (!silent) {{
          setBtnBusy(document.getElementById("btnAssetRefresh"), false, "刷新状态", "刷新中...");
        }}
      }}
    }}
    async function loadAssetReleases() {{
      const btn = document.getElementById("btnLoadReleases");
      const ra = document.getElementById("releasesArea");
      const rp = document.getElementById("releasesPlaceholder");
      const sel = document.getElementById("releaseSelect");
      if (!sel || !ra || !rp) return;
      if (btn) {{
        btn.disabled = true;
        btn.textContent = "加载中…";
      }}
      try {{
        const url = assetsProtoIsSl()
          ? "/api/snowluma/runtime/releases?limit=200"
          : "/api/runtime/releases?limit=200";
        const data = await api(url);
        const raw = Array.isArray(data.releases) ? data.releases : [];
        _assetReleaseList = raw
          .map((x) => {{
            const tn = String(x.tag_name || x.tag || "").trim();
            if (!tn) return null;
            return {{ ...x, tag_name: tn }};
          }})
          .filter(Boolean);
        if (!_assetReleaseList.length) {{
          sel.innerHTML = "";
          ra.style.display = "block";
          rp.style.display = "block";
          rp.textContent =
            "未获取到版本列表（请检查仓库配置、网络或 GitHub API 限流；可在配置中设置 pallas_protocol_github_token）。";
          const det = document.getElementById("releaseDetail");
          if (det) det.textContent = "";
          return;
        }}
        rp.style.display = "none";
        sel.innerHTML = _assetReleaseList.map((r) => {{
          const tag = r.tag_name;
          const label = tag + (r.prerelease ? " (pre)" : "") + (r.name && r.name !== tag ? " · " + r.name : "");
          return `<option value="${{invEsc(tag)}}">${{invEsc(label)}}</option>`;
        }}).join("");
        ra.style.display = "block";
        updateAssetReleaseDetail();
        sel.onchange = () => updateAssetReleaseDetail();
        if (typeof initShellPrettySelects === "function") initShellPrettySelects(ra);
        if (typeof shellPrettySyncSelect === "function") shellPrettySyncSelect(sel);
      }} catch (e) {{
        alert("加载 release 列表失败: " + (e.message || e));
      }} finally {{
        if (btn) {{
          btn.disabled = false;
          btn.textContent = "加载版本列表";
        }}
      }}
    }}
    function updateAssetReleaseDetail() {{
      const releases = _assetReleaseList || [];
      const sel = document.getElementById("releaseSelect");
      if (!sel) return;
      const tag = sel.value;
      const r = releases.find((x) => x.tag_name === tag);
      const el = document.getElementById("releaseDetail");
      if (!el) return;
      if (!r) {{ el.textContent = ""; return; }}
      const parts = [];
      if (r.published_at) parts.push("发布于 " + new Date(r.published_at).toLocaleDateString("zh-CN"));
      if (r.assets && r.assets.length) parts.push("资产: " + r.assets.map((a) => a.name).join(", "));
      el.textContent = parts.join(" · ");
    }}
    function fillRuntimeOverviewFromPayload(sl) {{
      if (!sl) sl = {{}};
      const job = sl.job || {{}};
      const d = sl.download || {{}};
      const manifest = sl.manifest || {{}};
      setText("rtStatus", statusText(job.status));
      setText("rtStage", stageText(job.message));
      const tag = pendingSnowlumaTag || job.tag || manifest.release_tag || d.tag || "";
      const assetEl = document.getElementById("rtAsset");
      if (assetEl) assetEl.title = String(d.asset || manifest.asset_name || "");
      setText("rtAsset", tag || d.asset || manifest.asset_name || "-");
      setText("rtMessage", job.message || "-");
      const repo = d.repo || "-";
      const tagHint = tag || d.tag || "latest";
      setText("rtSource", manifest.source_url ? manifest.source_url : `${{repo}} @ ${{tagHint}}`);
      setText("rtProgramDir", sl.effective_program_dir || manifest.program_dir || "-");
      setText("rtTime", new Date().toLocaleTimeString());
      const pre = document.getElementById("runtimeStatus");
      if (pre && !shouldPauseLiveLogDomWrite(pre)) pre.textContent = JSON.stringify(sl, null, 2);
    }}
    async function assetActivateSelectedTag() {{
      const sel = document.getElementById("releaseSelect");
      const tag = sel ? sel.value : "";
      if (!tag) {{ alert("请先选择版本"); return; }}
      if (assetsProtoIsSl()) {{
        try {{
          await api("/api/snowluma/runtime/activate-tag", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ tag }}),
          }});
          pendingSnowlumaTag = null;
          const slo = await api("/api/snowluma/runtime/overview");
          fillRuntimeOverviewFromPayload(slo);
          await loadAssetLocalInventory();
          alert("已将托管切换到版本 " + tag + "。");
        }} catch (e) {{
          const msg = String(e.message || e);
          if (msg.includes("未找到") && msg.includes("解压")) {{
            pendingSnowlumaTag = tag;
            setText("rtAsset", tag);
            setText("rtStatus", "待更新");
            setText("rtStage", "已选择");
            setText("rtMessage", "本地尚无该版本解压目录，已选中 " + tag + "，请点击「下载 / 更新」");
            setText("rtTime", new Date().toLocaleTimeString());
            const btn = document.getElementById("btnDownloadTag");
            if (btn) {{
              const prev = btn.textContent;
              btn.textContent = "✓ 待下载";
              setTimeout(() => {{ btn.textContent = prev; }}, 1500);
            }}
          }} else {{
            alert(msg);
          }}
        }}
        return;
      }}
      try {{
        await api("/api/runtime/activate-tag", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ tag }}),
        }});
        pendingTag = null;
        await refreshRuntime({{ silent: true }});
        await loadAssetLocalInventory();
        alert("已将托管切换到版本 " + tag + "。");
      }} catch (e) {{
        const msg = String(e.message || e);
        if (msg.includes("未找到") && msg.includes("解压")) {{
          pendingTag = tag;
          const detailEl = document.getElementById("releaseDetail");
          const assetHint = detailEl ? detailEl.textContent : "";
          setText("rtAsset", tag);
          setText("rtSource", assetHint ? "待下载: " + assetHint : "待下载: " + tag);
          setText("rtStatus", "待更新");
          setText("rtStage", "已选择");
          setText("rtMessage", "本地尚无该版本解压目录，已选中 " + tag + "，请点击「立即更新」下载");
          setText("rtTime", new Date().toLocaleTimeString());
          const btn = document.getElementById("btnDownloadTag");
          if (btn) {{
            const prev = btn.textContent;
            btn.textContent = "✓ 待下载";
            setTimeout(() => {{ btn.textContent = prev; }}, 1500);
          }}
        }} else {{
          alert(msg);
        }}
      }}
    }}
    async function downloadRuntime() {{
      const mode = String(document.getElementById("runtimeModeNapcat")?.value || "");
      if (mode === "docker") {{
        alert("Docker 模式无需下载发行包，请使用上方「NapCat Docker 镜像」旁的「拉取镜像」。");
        return;
      }}
      const dl = document.getElementById("btnAssetDownload");
      setBtnBusy(dl, true, "立即更新", "更新中...");
      try {{
        const tp = String(document.getElementById("targetPlatform")?.value || "auto");
        const modeQ = String(document.getElementById("runtimeModeNapcat")?.value || "");
        const qs = [];
        if (tp) qs.push("target_platform=" + encodeURIComponent(tp));
        if (modeQ) qs.push("runtime_mode=" + encodeURIComponent(modeQ));
        const url = pendingTag
          ? "/api/runtime/download?tag=" + encodeURIComponent(pendingTag) + (qs.length ? "&" + qs.join("&") : "")
          : "/api/runtime/download" + (qs.length ? "?" + qs.join("&") : "");
        await api(url, {{ method: "POST" }});
        pendingTag = null;
        await refreshRuntime();
        void loadAssetLocalInventory();
      }} catch (e) {{ alert(e.message); }}
      finally {{
        setBtnBusy(dl, false, "立即更新", "更新中...");
        syncAssetDownloadButtonText();
      }}
    }}
    async function rescanRuntime() {{
      if (assetsProtoIsSl()) return;
      setBtnBusy(document.getElementById("btnRescan"), true, "刷新检测", "检测中...");
      try {{
        await api("/api/runtime/rescan", {{ method: "POST" }});
        await refreshRuntime();
        void loadAssetLocalInventory();
      }} catch (e) {{ alert(e.message); }}
      finally {{
        setBtnBusy(document.getElementById("btnRescan"), false, "刷新检测", "检测中...");
      }}
    }}
    async function downloadSnowlumaRuntime() {{
      const dl = document.getElementById("btnAssetDownload");
      setBtnBusy(dl, true, "下载 / 更新", "处理中...");
      try {{
        const tp = String(document.getElementById("slTargetPlatform")?.value || "auto");
        try {{ localStorage.setItem("pallas_protocol_sl_target_platform", tp); }} catch (e) {{}}
        const qs = [];
        if (pendingSnowlumaTag) qs.push("tag=" + encodeURIComponent(pendingSnowlumaTag));
        if (tp && tp !== "auto") qs.push("target_platform=" + encodeURIComponent(tp));
        const q = qs.length ? ("?" + qs.join("&")) : "";
        await api("/api/snowluma/runtime/download" + q, {{ method: "POST" }});
        pendingSnowlumaTag = null;
        const slo = await api("/api/snowluma/runtime/overview");
        fillRuntimeOverviewFromPayload(slo);
        void loadAssetLocalInventory();
      }} catch (e) {{ alert(e.message || e); }}
      finally {{
        setBtnBusy(dl, false, "下载 / 更新", "处理中...");
        syncAssetDownloadButtonText();
      }}
    }}
{token_sync_js}
    loadRuntimeProfile().catch((e) => {{
      const rs = document.getElementById("runtimeStatus");
      if (rs && !shouldPauseLiveLogDomWrite(rs)) rs.textContent = "加载 profile 失败: " + String(e.message || e);
    }});
    assetRefreshOverview({{ silent: true }}).catch(() => {{}});
    setInterval(() => {{ void assetRefreshOverview({{ silent: true }}); }}, 1200);
  </script>
</body>
</html>
"""


def render_account_workspace(
    base_path: str,
    account_id: str,
    pallas_console_http_base: str = "/pallas",
    *,
    page_session: str = "",
) -> str:
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    aid = json.dumps(account_id)
    aid_h = html_escape(account_id, quote=True)
    common_api_js = _render_common_api_js()
    token_sync_js = _render_hidden_token_sync_js("backDash", page_session=page_session)
    shell_open = render_protocol_shell_open(
        path,
        pallas_console_http_base,
        active="",
        page_title=f"账号 {account_id}",
        page_desc="实例控制台",
    )
    shell_close = render_protocol_shell_close(path, active="", pallas_console_http_base=pallas_console_http_base)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
{shell_head_assets(path)}  <title>账号 {aid_h} · 协议端</title>
</head>
<body>
  <input type="hidden" id="token" value="" autocomplete="off" />
  {shell_open}
    <div class="layout-acc">
      <nav class="side" id="nav">
        <a href="#" class="active" data-tab="overview">概览</a>
        <a href="#" data-tab="settings">设置</a>
        <a href="#" data-tab="configs">原始配置</a>
        <a href="#" id="accLinkRuntime">协议资产</a>
      </nav>
      <div class="acc-main">
        <section class="panel active" id="panel-overview">
          <div class="card">
            <h3>状态</h3>
            <div id="ovBody" class="muted">加载中…</div>
            <div class="row" style="margin-top:14px">
              <button class="btn secondary" type="button" onclick="doStart()">启动</button>
              <button class="btn secondary" type="button" onclick="doStop()">停止</button>
              <button class="btn secondary" type="button" onclick="doRestart()">重启</button>
              <button class="btn danger" type="button" onclick="doDelete()">删除账号</button>
            </div>
            <div id="snowlumaInjectRow" class="row" style="margin-top:10px;display:none;flex-wrap:wrap;gap:10px;align-items:flex-start">
              <span class="muted" style="font-size:0.82rem;line-height:1.5">SnowLuma 需在<strong>自带 WebUI</strong>中对 QQ 进程<strong>首次手动加载/注入</strong>后，进程列表才会显示 UIN；请先使用上方「打开原生 WebUI」登录并完成首次注入。</span>
            </div>
          </div>
          <div class="card acc-qr-card" id="accQrCard" hidden style="margin-top:12px">
            <div class="acc-qr-card__hd row" style="justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;margin-bottom:10px">
              <div>
                <h3 style="margin:0">登录二维码</h3>
                <p class="muted acc-qr-card__hint" id="accQrHint" style="margin:4px 0 0;font-size:0.82rem">协议端已生成 PNG，可直接扫码登录</p>
              </div>
              <div class="row-actions acc-qr-card__actions">
                <a class="btn secondary" id="accQrOpenLink" href="#" target="_blank" rel="noopener noreferrer">新标签打开</a>
                <button class="btn secondary" type="button" onclick="pollAccQrcode(true)">刷新</button>
              </div>
            </div>
            <div class="acc-qr-card__body">
              <img id="accQrImg" class="acc-qr-card__img" alt="登录二维码" decoding="async" />
            </div>
          </div>
          <div class="card" style="margin-top:12px">
            <div class="row" style="justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px">
              <h3 style="margin:0">协议端进程</h3>
              <button class="btn secondary" type="button" onclick="copyLogText('accLogs')">复制</button>
            </div>
            <pre class="logs logs-protocol" id="accLogs" title="可鼠标框选复制">正在加载进程日志…</pre>
          </div>
          <div class="card" style="margin-top:12px">
            <div class="row" style="justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
              <p class="muted" style="margin:0">NoneBot 主进程日志（分片下数据量大，按需展开）</p>
              <button type="button" class="btn secondary" id="accNbToggleBtn">展开日志</button>
            </div>
            <div id="accNbLogSection" hidden>
            <div class="sl-runlog sl-runlog--account" id="accNbLogCard">
              <div class="sl-runlog-hd">
                <div class="sl-runlog-titles">
                  <h2 style="margin:0;font-size:1.05rem">运行日志<span class="sl-runlog-bad wait" id="accNbLogStreamBadge">未启用</span></h2>
                  <p style="margin:4px 0 0;font-size:0.78rem;color:var(--muted)" id="accNbLogSubLine">
                    最近 <span id="accNbLogFilteredN">0</span> / <span id="accNbLogTotalN">0</span> 条 · SSE
                  </p>
                </div>
                <div class="sl-runlog-tools">
                  <input type="search" id="accNbLogFilter" class="grow" placeholder="搜索消息 / 模块 / 级别" />
                  <select id="accNbLogScope" class="sl-runlog-scope" title="范围">
                    <option value="all">全部</option>
                    <option value="webui">控制台</option>
                    <option value="protocol">协议</option>
                  </select>
                  <button type="button" class="btn secondary" id="accNbLogPauseBtn">暂停</button>
                  <button type="button" class="btn secondary" id="accNbLogRefreshBtn">刷新</button>
                  <button type="button" class="btn secondary" id="accNbLogClearBtn">清空视图</button>
                  <button type="button" class="btn secondary" id="accNbLogCopyBtn">复制</button>
                </div>
              </div>
              <div class="sl-runlog-levels" id="accNbLogLevels"></div>
              <div class="sl-runlog-viewport" id="accNbLogViewport" title="可框选复制">
                <div class="sl-runlog-inner" id="accNbLogRows"></div>
              </div>
            </div>
            </div>
          </div>
        </section>
        <section class="panel" id="panel-settings">
          <div class="card">
            <h3>详细设置</h3>
            <p id="onebotHint" class="muted"></p>
            <p id="setMsg" class="muted"></p>
            <div class="field"><label>实例名</label><input id="display_name" /></div>
            <div class="field"><label>QQ（只读）</label><input id="qq" readonly /></div>
            <div class="field"><label>协议端类型</label>
              <select id="protocol_backend" class="shell-pretty-select">
                <option value="napcat">NapCat</option>
                <option value="snowluma">SnowLuma</option>
              </select>
            </div>
            <p class="muted" style="margin:-6px 0 10px;font-size:0.82rem">
              切换后启动命令与数据子目录会按后端调整；建议在进程已停止时修改并保存。
            </p>
            <div class="field" id="rowManagedRuntimeTag"><label>托管运行时版本</label>
              <select id="managed_runtime_tag" class="shell-pretty-select">
                <option value="">跟随全局默认（仪表盘当前托管）</option>
              </select>
            </div>
            <p class="muted" style="margin:-6px 0 10px;font-size:0.82rem;line-height:1.45">
              与协议资产页 <code>runtime_extract</code> 下子目录（Release 标签）一致；留空则跟随仪表盘全局托管。保存后需重启本账号协议进程。
            </p>
            <div class="field"><label>内置 WebUI 端口</label><input id="webui_port" type="number" /></div>
            <p id="webuiTokenHint" class="muted" style="display:none;margin:-4px 0 8px;font-size:0.82rem;white-space:pre-wrap"></p>
            <div class="field" id="rowWebuiToken"><label>内置 WebUI token</label><input id="webui_token" autocomplete="off" /></div>
            <div id="rowSnowlumaDockerVnc" style="display:none;margin-top:4px">
              <p class="muted" style="margin:0 0 10px;font-size:0.82rem;line-height:1.45">
                当前账号为 <strong>SnowLuma Linux Docker</strong> 时，<strong>OneBot HTTP/WS</strong> 与 <strong>noVNC / VNC</strong> 在留空时由服务端按已占用端口自动挑选宿主机端口（多实例互不冲突）。
                亦可在此手动指定 <strong>noVNC</strong>（浏览器桌面）与 <strong>VNC</strong>：<strong>填 0</strong> 表示不发布该映射，<strong>留空并保存</strong>则走自动或全局 <code>.env</code>。
              </p>
              <div class="field"><label>宿主机 noVNC 端口</label>
                <input id="snowluma_docker_host_novnc_port" type="number" min="0" max="65535" placeholder="留空=自动或全局" />
              </div>
              <div class="field"><label>宿主机 VNC 端口</label>
                <input id="snowluma_docker_host_vnc_port" type="number" min="0" max="65535" placeholder="留空=自动或全局" />
              </div>
            </div>
            <div id="snowlumaDockerPortMapCard" style="display:none;margin-top:12px;padding:12px 14px;border:1px solid var(--bd);border-radius:var(--radius);background:var(--bg1)">
              <div style="font-size:0.88rem;font-weight:700;color:var(--txt);margin-bottom:8px">SnowLuma Docker 端口映射</div>
              <p id="snowlumaDockerPortMapHint" class="muted" style="margin:0 0 8px;font-size:0.8rem;line-height:1.45"></p>
              <div id="snowlumaDockerPortMapTableWrap" style="overflow:auto;max-height:220px">
                <table class="acc-table" style="width:100%;border-collapse:collapse;font-size:0.82rem">
                  <thead><tr>
                    <th style="text-align:left;padding:6px 8px">服务</th>
                    <th style="text-align:left;padding:6px 8px">宿主机</th>
                    <th style="text-align:left;padding:6px 8px">容器内</th>
                  </tr></thead>
                  <tbody id="snowlumaDockerPortMapBody"></tbody>
                </table>
              </div>
            </div>
            <hr style="border:none;border-top:1px solid var(--bd);margin:6px 0 14px" />
            <h4 style="margin:0 0 12px;font-size:0.9rem;color:var(--muted);font-weight:700">WS 连接（协议端 → Bot）</h4>
            <p class="muted" style="margin:0 0 12px">正向 WS：协议端主动连接牛牛时使用的地址。跨机部署时填写牛牛所在机器对本机可达的地址；保存后<strong>重启协议端进程</strong>生效，无需重启牛牛。</p>
            <div class="field"><label>WS 连接地址</label>
              <input id="ws_url" placeholder="ws://bot-host:8088/onebot/v11/ws" autocomplete="off" />
            </div>
            <div class="field"><label id="lblWsName">连接名（协议端侧显示）</label>
              <input id="ws_name" placeholder="pallas" autocomplete="off" />
            </div>
            <div class="field"><label>WS Token（与 Bot 侧 access_token 一致）</label>
              <input id="ws_token" type="password" autocomplete="off" placeholder="留空则不鉴权" />
            </div>
            <div class="row">
              <button class="btn" type="button" onclick="saveSettings()">保存</button>
            </div>
          </div>
        </section>
        <section class="panel" id="panel-configs">
          <div class="card">
            <h3>原始配置</h3>
            <p id="cfgProtocolDirtyHint" class="muted" style="display:none;margin:-4px 0 10px;color:#b45309">
              当前选择的协议端类型与已保存不一致：请先回到「设置」保存协议类型，再编辑下方 JSON。
            </p>
            <p id="cfgMsg" class="muted"></p>
            <div class="field"><label>onebot</label><textarea class="cfg mono" id="tj_onebot"></textarea></div>
            <div class="field" id="rowCfgMid"><label id="lblCfgMid">napcat</label><textarea class="cfg mono" id="tj_napcat"></textarea></div>
            <div class="field" id="rowCfgWebui"><label>webui</label><textarea class="cfg mono" id="tj_webui"></textarea></div>
            <button class="btn" type="button" onclick="saveConfigs()">保存 JSON</button>
          </div>
        </section>
      </div>
    </div>
{shell_close}
  <script>
    const basePath = {p};
    const accountId = {aid};
    let accountProcessRunning = false;
{common_api_js}
    initPallasShellThemeFromStorage();
    applyShellUiPrefsFromStorage();
    const ACC_NB_LEVELS = ["debug", "info", "success", "warn", "error"];
    let accNbLogEntries = [];
    let accNbLogPaused = false;
    let accNbLogFilter = "";
    let accNbLogLevels = new Set(ACC_NB_LEVELS);
    let accNbLogEs = null;
    let accNbLogExpanded = false;
    let accNbLogLoading = false;
    let accNbLogRenderDeferred = false;
    let accNbRenderScheduled = 0;
    const ACC_NB_MAX_ENTRIES = 80;
    function accNbFormatTime(iso) {{
      try {{
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return String(iso || "");
        return d.toLocaleTimeString();
      }} catch (e) {{ return String(iso || ""); }}
    }}
    function accNbStreamBadge(text, kind) {{
      const el = document.getElementById("accNbLogStreamBadge");
      if (!el) return;
      el.textContent = text;
      el.className = "sl-runlog-bad " + (kind === "ok" ? "ok" : kind === "err" ? "err" : "wait");
    }}
    function accNbLevelUiClass(lv) {{
      const u = String(lv || "").toLowerCase();
      if (u === "debug") return "sl-lv-debug";
      if (u === "success") return "sl-lv-success";
      if (u === "warn") return "sl-lv-warn";
      if (u === "error") return "sl-lv-error";
      return "sl-lv-info";
    }}
    function accNbFiltered() {{
      const f = (accNbLogFilter || "").trim().toLowerCase();
      return accNbLogEntries.filter((x) => {{
        if (!accNbLogLevels.has(String(x.level || "").toLowerCase())) return false;
        if (!f) return true;
        const m = String(x.message || "").toLowerCase();
        const sc = String(x.scope || "").toLowerCase();
        const lv = String(x.level || "").toLowerCase();
        return m.includes(f) || sc.includes(f) || lv.includes(f);
      }});
    }}
    function accNbShouldPauseDom() {{
      const vp = document.getElementById("accNbLogViewport");
      if (!vp) return false;
      if (isLogElementUserSelecting(vp)) return true;
      return false;
    }}
    function accNbRender() {{
      const rows = document.getElementById("accNbLogRows");
      const sub = document.getElementById("accNbLogFilteredN");
      const tot = document.getElementById("accNbLogTotalN");
      if (tot) tot.textContent = String(accNbLogEntries.length);
      const list = accNbFiltered();
      if (sub) sub.textContent = String(list.length);
      if (!rows) return;
      if (!list.length) {{
        rows.innerHTML = '<div class="sl-runlog-empty">暂无日志</div>';
        return;
      }}
      rows.innerHTML = list.slice(-ACC_NB_MAX_ENTRIES).map((x) => {{
        const lv = String(x.level || "").toUpperCase();
        const t = accNbFormatTime(x.time);
        const sc = escHtml(x.scope || "");
        const msg = escHtml(x.message || "");
        const lc = accNbLevelUiClass(x.level);
        return `<div class="sl-runlog-row"><span class="sl-runlog-t">${{t}}</span><span class="sl-runlog-lv ${{lc}}">${{lv}}</span><span class="sl-runlog-sc">[${{sc}}]</span><span class="sl-runlog-msg">${{msg}}</span></div>`;
      }}).join("");
    }}
    function flushDeferredAccNbLogRender() {{
      if (!accNbLogRenderDeferred || !accNbLogExpanded) return;
      accNbLogRenderDeferred = false;
      scheduleAccNbRender();
    }}
    function scheduleAccNbRender() {{
      if (!accNbSnapshotExpanded()) return;
      if (accNbRenderScheduled) return;
      if (accNbShouldPauseDom()) {{
        accNbLogRenderDeferred = true;
        return;
      }}
      accNbRenderScheduled = requestAnimationFrame(() => {{
        accNbRenderScheduled = 0;
        if (accNbShouldPauseDom()) {{
          accNbLogRenderDeferred = true;
          return;
        }}
        accNbRender();
        accNbSyncViewportLayout();
        accNbScrollToEnd();
      }});
    }}
    function accNbSnapshotExpanded() {{
      return accNbLogExpanded;
    }}
    function accNbScrollToEnd() {{
      if (accNbLogPaused) return;
      if (accNbShouldPauseDom()) return;
      const vp = document.getElementById("accNbLogViewport");
      if (vp) vp.scrollTop = vp.scrollHeight;
    }}
    function accNbSyncViewportLayout() {{
      const card = document.getElementById("accNbLogCard");
      const vp = document.getElementById("accNbLogViewport");
      if (!card || !vp || !accNbLogExpanded) return;
      const cardStyle = getComputedStyle(card);
      const gap = parseFloat(cardStyle.rowGap || cardStyle.gap || "10") || 10;
      const padY = parseFloat(cardStyle.paddingTop) + parseFloat(cardStyle.paddingBottom);
      let siblings = 0;
      let siblingCount = 0;
      for (const el of card.children) {{
        if (el === vp) continue;
        siblings += el.getBoundingClientRect().height;
        siblingCount += 1;
      }}
      const avail = card.clientHeight - padY - gap * siblingCount - siblings;
      if (avail > 72) vp.style.height = `${{Math.floor(avail)}}px`;
      else vp.style.height = "";
    }}
    function accNbInitLevelPills() {{
      const host = document.getElementById("accNbLogLevels");
      if (!host) return;
      host.innerHTML = ACC_NB_LEVELS.map((lv) =>
        `<button type="button" data-acc-nb-lv="${{lv}}" class="on">${{String(lv).toUpperCase()}}</button>`
      ).join("");
      host.querySelectorAll("[data-acc-nb-lv]").forEach((btn) => {{
        btn.addEventListener("click", () => {{
          const lv = btn.getAttribute("data-acc-nb-lv");
          if (accNbLogLevels.has(lv)) accNbLogLevels.delete(lv);
          else accNbLogLevels.add(lv);
          btn.classList.toggle("on", accNbLogLevels.has(lv));
          btn.classList.toggle("off", !accNbLogLevels.has(lv));
          scheduleAccNbRender();
        }});
      }});
    }}
    async function accNbEnsureStarted() {{
      if (!accNbLogExpanded || accNbLogLoading) return;
      accNbLogLoading = true;
      try {{
        await accNbLoadInitial();
        accNbStartSse();
      }} finally {{
        accNbLogLoading = false;
      }}
    }}
    async function accNbLoadInitial() {{
      const scopeEl = document.getElementById("accNbLogScope");
      const sc = scopeEl ? scopeEl.value : "all";
      const data = await api(`/api/nonebot-logs?lines=60&scope=${{encodeURIComponent(sc)}}`);
      accNbLogEntries = Array.isArray(data.entries) ? data.entries.slice(-ACC_NB_MAX_ENTRIES) : [];
      if (accNbLogExpanded) {{
        accNbRender();
        accNbSyncViewportLayout();
        accNbScrollToEnd();
      }} else {{
        scheduleAccNbRender();
      }}
    }}
    function accNbClear() {{
      if (!confirm("清空当前日志视图？仅影响浏览器展示，不清服务端缓冲。")) return;
      accNbLogEntries = [];
      accNbRender();
    }}
    function accNbCopy() {{
      const lines = accNbFiltered().map((x) =>
        `${{accNbFormatTime(x.time)}} ${{String(x.level || "").toUpperCase()}} [${{x.scope}}] ${{x.message}}`
      );
      const t = lines.join("\\n");
      if (!String(t).trim()) {{ notify("当前无可复制内容", "warn"); return; }}
      navigator.clipboard.writeText(t).then(() => notify("已复制", "ok")).catch((e) => notify(String(e.message || e), "err"));
    }}
    function accNbStopSse() {{
      if (accNbLogEs) {{
        try {{ accNbLogEs.close(); }} catch (e) {{}}
        accNbLogEs = null;
      }}
    }}
    function accNbStartSse() {{
      accNbStopSse();
      const tok = getSessionToken();
      const scopeEl = document.getElementById("accNbLogScope");
      const sc = scopeEl ? scopeEl.value : "all";
      let url = `${{basePath}}/api/nonebot-logs/stream?scope=${{encodeURIComponent(sc)}}`;
      if (tok) url += `&token=${{encodeURIComponent(tok)}}`;
      accNbStreamBadge("连接中", "wait");
      const es = new EventSource(url);
      accNbLogEs = es;
      es.onopen = () => accNbStreamBadge("实时", "ok");
      es.onerror = () => accNbStreamBadge("重连中", "err");
      es.onmessage = (ev) => {{
        try {{
          const row = JSON.parse(ev.data);
          if (row && row.type === "ready") return;
          if (!row || typeof row.id !== "number") return;
          if (accNbLogPaused) return;
          accNbLogEntries = [...accNbLogEntries.filter((it) => it.id !== row.id), row].slice(-ACC_NB_MAX_ENTRIES);
          scheduleAccNbRender();
        }} catch (e) {{}}
      }};
    }}
    function accNbWireRunlogUi() {{
      accNbInitLevelPills();
      document.getElementById("accNbLogFilter")?.addEventListener("input", (e) => {{
        accNbLogFilter = (e.target && e.target.value) || "";
        scheduleAccNbRender();
      }});
      document.getElementById("accNbLogPauseBtn")?.addEventListener("click", () => {{
        accNbLogPaused = !accNbLogPaused;
        const b = document.getElementById("accNbLogPauseBtn");
        if (b) b.textContent = accNbLogPaused ? "继续" : "暂停";
        if (!accNbLogPaused) accNbScrollToEnd();
      }});
      document.getElementById("accNbLogRefreshBtn")?.addEventListener("click", () => {{
        accNbLoadInitial().catch((e) => notify(e.message || e, "err"));
      }});
      document.getElementById("accNbLogClearBtn")?.addEventListener("click", accNbClear);
      document.getElementById("accNbLogCopyBtn")?.addEventListener("click", accNbCopy);
      document.getElementById("accNbLogScope")?.addEventListener("change", () => {{
        if (!accNbLogExpanded) return;
        accNbStopSse();
        accNbEnsureStarted().catch((e) => notify(String(e.message || e), "err"));
      }});
      document.getElementById("accNbToggleBtn")?.addEventListener("click", () => {{
        accNbLogExpanded = !accNbLogExpanded;
        const sec = document.getElementById("accNbLogSection");
        const btn = document.getElementById("accNbToggleBtn");
        if (sec) sec.hidden = !accNbLogExpanded;
        if (btn) btn.textContent = accNbLogExpanded ? "收起日志" : "展开日志";
        if (accNbLogExpanded) {{
          accNbEnsureStarted().then(() => {{
            flushDeferredAccNbLogRender();
            accNbRender();
            requestAnimationFrame(() => {{
              accNbSyncViewportLayout();
              requestAnimationFrame(() => accNbScrollToEnd());
            }});
          }}).catch((e) => notify(String(e.message || e), "err"));
        }} else {{
          accNbStopSse();
          accNbStreamBadge("未启用", "wait");
          const vp = document.getElementById("accNbLogViewport");
          if (vp) vp.style.height = "";
        }}
      }});
      window.addEventListener("resize", () => {{
        if (!accNbLogExpanded) return;
        accNbSyncViewportLayout();
      }});
    }}
    let activeTab = "overview";
    function tab(name) {{
      activeTab = name;
      document.querySelectorAll(".panel").forEach((el) => el.classList.remove("active"));
      document.getElementById("panel-" + name).classList.add("active");
      document.querySelectorAll(".side a[data-tab]").forEach((a) => a.classList.toggle("active", a.dataset.tab === name));
      const q = "tab=" + encodeURIComponent(name);
      history.replaceState(null, "", `${{basePath}}/account/${{encodeURIComponent(accountId)}}?${{q}}`);
      if (name !== "overview") {{
        accNbStopSse();
      }}
      if (name === "settings") loadHints();
      if (name === "configs") {{
        loadJsonCfgs().catch(() => {{}});
        updateCfgDirtyHint();
      }}
    }}
    document.getElementById("protocol_backend").addEventListener("change", () => {{
      applySettingsForProtocolSelect();
    }});
    document.getElementById("nav").addEventListener("click", (e) => {{
      const a = e.target.closest("a[data-tab]");
      if (!a) return;
      e.preventDefault();
      tab(a.dataset.tab);
    }});
    document.getElementById("accLinkRuntime").addEventListener("click", (e) => {{
      e.preventDefault();
      const q = __savedAccountBackend === "snowluma" ? "?protocol=snowluma" : "?protocol=napcat";
      location.href = `${{basePath}}/assets${{q}}`;
    }});
    function escHtml(s) {{
      return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }}
    let accQrLastUpdated = 0;
    let accQrObjectUrl = "";
    function accQrcodeFetchUrl(ts) {{
      let url = `${{basePath}}/api/accounts/${{encodeURIComponent(accountId)}}/qrcode`;
      const q = [];
      const tok = getSessionToken();
      if (tok) q.push(`token=${{encodeURIComponent(tok)}}`);
      if (ts) q.push(`t=${{encodeURIComponent(String(ts))}}`);
      if (q.length) url += "?" + q.join("&");
      return url;
    }}
    async function loadAccQrcodeImage(ts) {{
      const img = document.getElementById("accQrImg");
      const hint = document.getElementById("accQrHint");
      const link = document.getElementById("accQrOpenLink");
      const url = accQrcodeFetchUrl(ts);
      if (link) link.href = url;
      if (!img) return;
      const headers = {{}};
      const tok = getSessionToken();
      if (tok) headers["X-Pallas-Protocol-Token"] = tok;
      const res = await fetch(url, {{ credentials: "same-origin", headers }});
      if (!res.ok) throw new Error((await res.text()) || String(res.status));
      const blob = await res.blob();
      if (accQrObjectUrl) {{
        try {{ URL.revokeObjectURL(accQrObjectUrl); }} catch (e) {{}}
      }}
      accQrObjectUrl = URL.createObjectURL(blob);
      img.src = accQrObjectUrl;
      img.onerror = () => {{
        if (hint) hint.textContent = "二维码加载失败，请点「刷新」重试";
      }};
    }}
    async function pollAccQrcode(force) {{
      const card = document.getElementById("accQrCard");
      const hint = document.getElementById("accQrHint");
      try {{
        const meta = await api(`/api/accounts/${{encodeURIComponent(accountId)}}/qrcode/meta`);
        const pngNow = !!(meta && meta.exists);
        if (!pngNow) {{
          if (card) card.hidden = true;
          accQrLastUpdated = 0;
          return;
        }}
        const ts = meta.updated_at || 0;
        if (force || ts !== accQrLastUpdated) {{
          accQrLastUpdated = ts;
          if (card) card.hidden = false;
          await loadAccQrcodeImage(ts);
          if (hint && ts) {{
            try {{
              hint.textContent = "更新于 " + new Date(ts * 1000).toLocaleString() + " · 可直接扫码";
            }} catch (e) {{}}
          }}
        }}
      }} catch (e) {{
        if (card && force) card.hidden = true;
        if (hint && force) hint.textContent = String(e.message || e);
      }}
    }}
    async function bootAccountOverview() {{
      pollAccLogs().catch((e) => notify(String(e.message || e), "err"));
      pollAccQrcode(true).catch(() => {{}});
      try {{
        await loadAccount({{ brief: true }});
      }} catch (e) {{
        notify(String(e.message || e), "err");
      }}
      loadAccount({{ brief: false }}).catch((e) => notify(String(e.message || e), "err"));
    }}
    let __savedAccountBackend = "napcat";
    window.__managedTagSaved = "";
    async function fillManagedRuntimeTagSelect() {{
      const sel = document.getElementById("managed_runtime_tag");
      if (!sel) return;
      const saved = window.__managedTagSaved || "";
      try {{
        const path = currentProtocolSelect() === "snowluma"
          ? "/api/snowluma/runtime/local-inventory"
          : "/api/runtime/local-inventory";
        const data = await api(path);
        const dirs = Array.isArray(data.extract_dirs) ? data.extract_dirs : [];
        const names = dirs.map((d) => d.name).filter(Boolean);
        const parts = ['<option value="">跟随全局默认（仪表盘当前托管）</option>'];
        for (const n of names) {{
          const enc = String(n).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
          parts.push(`<option value="${{enc}}">${{escHtml(n)}}</option>`);
        }}
        sel.innerHTML = parts.join("");
        sel.value = saved && names.includes(saved) ? saved : "";
      }} catch (e) {{
        sel.innerHTML = '<option value="">（加载失败）</option>';
      }}
      if (typeof shellPrettySyncSelect === "function") shellPrettySyncSelect(sel);
    }}
    function currentProtocolSelect() {{
      return (document.getElementById("protocol_backend").value || "napcat").trim().toLowerCase() === "snowluma" ? "snowluma" : "napcat";
    }}
    function applySettingsForProtocolSelect() {{
      const isSl = currentProtocolSelect() === "snowluma";
      const row = document.getElementById("rowWebuiToken");
      if (row) row.style.display = isSl ? "none" : "";
      updateCfgDirtyHint();
      void fillManagedRuntimeTagSelect();
    }}
    function syncSnowlumaDockerVncRow(account) {{
      const rowD = document.getElementById("rowSnowlumaDockerVnc");
      if (!rowD) return;
      const show = !!(account && account.snowluma_linux_docker);
      rowD.style.display = show ? "block" : "none";
      if (!show) return;
      const nn = document.getElementById("snowluma_docker_host_novnc_port");
      const vv = document.getElementById("snowluma_docker_host_vnc_port");
      const gn = account.snowluma_docker_host_novnc_port;
      const gv = account.snowluma_docker_host_vnc_port;
      if (nn) nn.value = (gn !== undefined && gn !== null && String(gn).trim() !== "") ? String(gn) : "";
      if (vv) vv.value = (gv !== undefined && gv !== null && String(gv).trim() !== "") ? String(gv) : "";
    }}
    function syncSnowlumaDockerPortMapCard(account) {{
      const card = document.getElementById("snowlumaDockerPortMapCard");
      const hint = document.getElementById("snowlumaDockerPortMapHint");
      const body = document.getElementById("snowlumaDockerPortMapBody");
      if (!card || !body) return;
      const sp = account && account.snowluma_publish_ports;
      const items = sp && Array.isArray(sp.items) ? sp.items : [];
      const show = !!(account && account.snowluma_linux_docker && items.length);
      card.style.display = show ? "block" : "none";
      if (!show) return;
      const host = String((sp && sp.bind_host) || "127.0.0.1").trim() || "127.0.0.1";
      if (hint) {{
        hint.textContent = "宿主机 " + escHtml(host) + " 上映射到容器内端口如下；保存设置并重启本账号协议进程后生效。";
      }}
      body.innerHTML = items.map((row) => {{
        const lab = escHtml(row.label || "");
        const hp = escHtml(String(row.host ?? ""));
        const cp = escHtml(String(row.container ?? ""));
        return "<tr><td style=\\"padding:6px 8px\\">" + lab + "</td>"
          + "<td style=\\"padding:6px 8px;font-family:var(--font-mono,monospace)\\">" + escHtml(host) + ":" + hp + "</td>"
          + "<td style=\\"padding:6px 8px;font-family:var(--font-mono,monospace)\\">" + cp + "</td></tr>";
      }}).join("");
    }}
    function applyConfigsPanelForSavedBackend() {{
      const isSl = __savedAccountBackend === "snowluma";
      const lbl = document.getElementById("lblCfgMid");
      if (lbl) lbl.textContent = isSl ? "runtime（SnowLuma）" : "napcat（NapCat）";
      const rowW = document.getElementById("rowCfgWebui");
      if (rowW) rowW.style.display = isSl ? "none" : "";
    }}
    function updateCfgDirtyHint() {{
      const h = document.getElementById("cfgProtocolDirtyHint");
      if (!h) return;
      h.style.display = currentProtocolSelect() !== __savedAccountBackend ? "block" : "none";
    }}
    async function loadHints() {{
      try {{
        const h = await api("/api/connection-hints");
        const el = document.getElementById("onebotHint");
        if (!h.onebot_configured) {{
          el.textContent = "OneBot 未就绪：请检查 .env 中 HOST / PORT / ACCESS_TOKEN。";
          return;
        }}
        el.textContent = "当前连接: " + h.onebot_ws_url;
      }} catch (err) {{
        document.getElementById("onebotHint").textContent = String(err.message || err);
      }}
    }}
    async function loadAccount(opts) {{
      const ov = document.getElementById("ovBody");
      const brief = !!(opts && opts.brief);
      const q = brief ? "?brief=1" : "";
      try {{
        const data = await api(`/api/accounts/${{encodeURIComponent(accountId)}}${{q}}`);
        const a = data.account;
        accountProcessRunning = !!a.process_running;
      let st = "";
      if (a.process_running) {{
        st = "运行中 · PID：" + (a.pid || "—");
        if (a.connected) st += " · 已连接";
      }} else if (a.running) {{
        st = "已连接（进程可能已脱离）";
      }} else if (a.launch_ready) {{
        st = "已停止";
      }} else {{
        st = (a.launch_issues || []).join("; ");
      }}
      const wu = a.native_webui_url || "";
      const note = a.native_webui_auth_note || "";
      const rtpw = a.snowluma_runtime_webui_password || "";
      let html = "<div><strong>" + String(st).replace(/</g, "&lt;") + "</strong></div>";
      html += '<div class="muted" style="margin-top:8px">版本: ' + escHtml(a.runtime_version || "未知") + "</div>";
      if (wu) {{
        html += '<div style="margin-top:8px"><a href="' + escHtml(wu) + '" target="_blank" rel="noopener">打开原生 WebUI</a></div>';
      }}
      if (a.snowluma_linux_docker) {{
        const nv = a.snowluma_docker_novnc;
        if (nv && nv.url) {{
          const defPw = !!nv.uses_default_vnc_password;
          html += '<div style="margin-top:10px;padding:10px 12px;border:1px solid var(--bd);border-radius:var(--radius);background:var(--bg1);max-width:640px">';
          html += '<div style="font-weight:700;font-size:0.92rem;margin-bottom:6px;color:var(--txt)">SnowLuma 桌面（noVNC）</div>';
          html += '<p class="muted" style="margin:0 0 8px;font-size:0.82rem;line-height:1.5">请在容器<strong>启动后</strong>使用下方链接进入桌面；在 noVNC 中连接 VNC 时填写口令。'
            + (defPw ? ' 未设置全局 <code>PALLAS_PROTOCOL_SNOWLUMA_DOCKER_VNC_PASSWD</code> 时，默认口令为 <span class="mono">vncpasswd</span>。' : ' 口令以服务端 <code>PALLAS_PROTOCOL_SNOWLUMA_DOCKER_VNC_PASSWD</code> 为准。')
            + '</p>';
          html += '<div style="margin-top:4px"><a class="btn secondary" href="' + escHtml(String(nv.url)) + '" target="_blank" rel="noopener">打开 noVNC</a>'
            + '<span class="muted" style="margin-left:10px;font-size:0.78rem">无法打开时可尝试同端口根路径 <span class="mono">/</span></span></div>';
          html += '</div>';
        }} else {{
          html += '<div class="muted" style="margin-top:8px;font-size:0.82rem;line-height:1.45">SnowLuma Docker：当前未发布 noVNC 宿主机端口，浏览器无法进桌面；请到「设置」填写或留空以自动分配端口。</div>';
        }}
      }}
      if (note) {{
        html += '<div class="muted" style="margin-top:8px;white-space:pre-wrap">' + escHtml(note) + "</div>";
      }}
      if (rtpw) {{
        const u = (a.snowluma_webui_default_user || "").trim();
        const ubit = u ? ('<span class="muted">用户名</span> <span class="mono">' + escHtml(u) + '</span> <span class="muted">·</span> ') : "";
        html += '<div class="row" style="margin-top:8px;flex-wrap:wrap;gap:8px;align-items:center">' + ubit + '<span class="muted">初始口令</span> <span class="mono">' + escHtml(rtpw) + '</span> <button type="button" class="btn secondary" data-copy-plain="' + encodeURIComponent(rtpw) + '">复制</button></div>';
      }}
      html += '<div class="muted" style="margin-top:8px">WORKDIR: ' + escHtml(a.account_data_dir || "") + "</div>";
      ov.innerHTML = html;
      if (brief) return;
      document.getElementById("display_name").value = a.display_name || "";
      document.getElementById("qq").value = a.qq || "";
      {{
        const pb = (a.protocol_backend || "napcat").toString().trim().toLowerCase();
        document.getElementById("protocol_backend").value = pb === "snowluma" ? "snowluma" : "napcat";
        __savedAccountBackend = pb === "snowluma" ? "snowluma" : "napcat";
        if (typeof shellPrettySyncSelect === "function") {{
          const s = document.getElementById("protocol_backend");
          if (s) shellPrettySyncSelect(s);
        }}
      }}
      window.__managedTagSaved = (a.managed_runtime_tag || "").trim();
      applySettingsForProtocolSelect();
      applyConfigsPanelForSavedBackend();
      document.getElementById("webui_port").value = a.webui_port != null ? String(a.webui_port) : "";
      document.getElementById("webui_token").value = a.webui_token || "";
      syncSnowlumaDockerVncRow(a);
      syncSnowlumaDockerPortMapCard(a);
      {{
        const hint = document.getElementById("webuiTokenHint");
        if (hint) {{
          const pb = (a.protocol_backend || "napcat").toString().trim().toLowerCase();
          if (pb === "snowluma" && !a.snowluma_runtime_webui_password && a.native_webui_auth_note) {{
            hint.textContent = a.native_webui_auth_note;
            hint.style.display = "block";
          }} else {{
            hint.textContent = "";
            hint.style.display = "none";
          }}
        }}
      }}
      document.getElementById("ws_url").value = a.ws_url || "";
      document.getElementById("ws_name").value = a.ws_name || "";
      document.getElementById("ws_token").value = a.ws_token || "";
        {{
          const row = document.getElementById("snowlumaInjectRow");
          if (row) {{
            const pb = (a.protocol_backend || "napcat").toString().trim().toLowerCase();
            row.style.display = pb === "snowluma" ? "flex" : "none";
          }}
        }}
      }} catch (e) {{
        const msg = String(e.message || e);
        if (ov) ov.innerHTML = '<div class="muted">加载失败：' + escHtml(msg) + "</div>";
        notify(msg, "err");
      }}
    }}
    async function pollAccLogs() {{
      try {{
        const data = await api(`/api/accounts/${{encodeURIComponent(accountId)}}/logs?lines=120`);
        const el = document.getElementById("accLogs");
        if (shouldPauseLiveLogDomWrite(el)) return;
        const lines = data.logs || [];
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
        el.textContent = lines.length ? lines.join("\\n") : "暂无进程输出";
        if (atBottom) el.scrollTop = el.scrollHeight;
      }} catch (e) {{
        const el = document.getElementById("accLogs");
        if (!shouldPauseLiveLogDomWrite(el)) el.textContent = String(e.message || e);
      }}
    }}
    async function loadJsonCfgs() {{
      const c = await api(`/api/accounts/${{encodeURIComponent(accountId)}}/configs`);
      document.getElementById("tj_onebot").value = JSON.stringify(c.onebot || {{}}, null, 2);
      if (__savedAccountBackend === "snowluma") {{
        document.getElementById("tj_napcat").value = JSON.stringify(c.runtime || {{}}, null, 2);
        document.getElementById("tj_webui").value = "";
      }} else {{
        document.getElementById("tj_napcat").value = JSON.stringify(c.napcat || {{}}, null, 2);
        document.getElementById("tj_webui").value = JSON.stringify(c.webui || {{}}, null, 2);
      }}
    }}
    async function saveSettings() {{
      const el = document.getElementById("setMsg");
      el.textContent = "";
      try {{
        const wport = document.getElementById("webui_port").value.trim();
        const wn = parseInt(wport, 10);
        const pbSave = (document.getElementById("protocol_backend").value || "napcat").trim().toLowerCase();
        const body = {{
          display_name: document.getElementById("display_name").value.trim(),
          protocol_backend: pbSave === "snowluma" ? "snowluma" : "napcat",
          managed_runtime_tag: (document.getElementById("managed_runtime_tag") || {{}}).value || "",
          ws_url: document.getElementById("ws_url").value.trim(),
          ws_name: document.getElementById("ws_name").value.trim(),
          ws_token: document.getElementById("ws_token").value,
        }};
        if (pbSave !== "snowluma") {{
          body.webui_token = document.getElementById("webui_token").value.trim();
        }} else {{
          const rowD = document.getElementById("rowSnowlumaDockerVnc");
          if (rowD && rowD.style.display !== "none") {{
            const nns = String((document.getElementById("snowluma_docker_host_novnc_port") || {{}}).value || "").trim();
            const vvs = String((document.getElementById("snowluma_docker_host_vnc_port") || {{}}).value || "").trim();
            body.snowluma_docker_host_novnc_port = nns === "" ? null : parseInt(nns, 10);
            body.snowluma_docker_host_vnc_port = vvs === "" ? null : parseInt(vvs, 10);
          }}
        }}
        if (wport && !Number.isNaN(wn)) body.webui_port = wn;
        let restartNow = true;
        if (accountProcessRunning) {{
          restartNow = confirm("当前账号正在运行，保存后需要重启进程才能生效。是否立即重启？");
        }}
        showPageLoading("保存中…");
        const put = await api(`/api/accounts/${{encodeURIComponent(accountId)}}?restart=${{restartNow ? "1" : "0"}}`, {{
          method: "PUT", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify(body),
        }});
        showPageLoading("读取最新数据…");
        await loadAccount();
        el.textContent = put.restarted ? "已保存并已重启进程。" : (put.needs_restart ? "已保存，重启后生效。" : "已保存。");
        notify(el.textContent, "ok");
      }} catch (e) {{
        el.textContent = String(e.message || e);
      }} finally {{
        hidePageLoading();
      }}
    }}
    async function saveConfigs() {{
      const el = document.getElementById("cfgMsg");
      el.textContent = "";
      try {{
        if (currentProtocolSelect() !== __savedAccountBackend) {{
          const msg = "请先在「设置」中保存协议端类型，再保存原始配置。";
          el.textContent = msg;
          notify(msg, "warn");
          return;
        }}
        let payload;
        if (__savedAccountBackend === "snowluma") {{
          payload = {{
            onebot: JSON.parse(document.getElementById("tj_onebot").value || "{{}}"),
            runtime: JSON.parse(document.getElementById("tj_napcat").value || "{{}}"),
          }};
        }} else {{
          payload = {{
            onebot: JSON.parse(document.getElementById("tj_onebot").value || "{{}}"),
            napcat: JSON.parse(document.getElementById("tj_napcat").value || "{{}}"),
            webui: JSON.parse(document.getElementById("tj_webui").value || "{{}}"),
          }};
        }}
        let restartNow = true;
        if (accountProcessRunning) {{
          restartNow = confirm("当前账号正在运行，配置变更需重启后生效。是否立即重启？");
        }}
        showPageLoading("保存中…");
        const cfgPut = await api(`/api/accounts/${{encodeURIComponent(accountId)}}/configs?restart=${{restartNow ? "1" : "0"}}`, {{
          method: "PUT", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify(payload),
        }});
        showPageLoading("读取最新数据…");
        await loadJsonCfgs();
        el.textContent = cfgPut.restarted ? "已写入磁盘并已重启进程。" : (cfgPut.needs_restart ? "已写入磁盘，重启后生效。" : "已写入磁盘。");
        notify(el.textContent, "ok");
      }} catch (e) {{
        el.textContent = String(e.message || e);
      }} finally {{
        hidePageLoading();
      }}
    }}
    function showPageLoading(label = "加载中…") {{
      const ov = document.getElementById("pageOverlay");
      const lb = document.getElementById("pageOverlayLabel");
      if (lb) lb.textContent = label;
      if (ov) ov.classList.add("visible");
    }}
    function hidePageLoading() {{
      const ov = document.getElementById("pageOverlay");
      if (ov) ov.classList.remove("visible");
    }}
    function notify(msg, level = "ok") {{
      const host = document.getElementById("statusbar");
      const el = document.createElement("div");
      el.className = `toast ${{level}}`;
      el.textContent = String(msg || "");
      host.appendChild(el);
      setTimeout(() => el.remove(), 4200);
    }}
    function copyLogText(id) {{
      const el = document.getElementById(id);
      const t = (el && el.textContent) ? el.textContent : "";
      if (!String(t).trim()) {{ notify("当前无内容可复制", "warn"); return; }}
      navigator.clipboard.writeText(t).then(() => notify("已复制到剪贴板", "ok"))
        .catch((e) => notify(String(e.message || e), "err"));
    }}
    function accBtnLoad(btn, text) {{
      if (!btn) return;
      btn.disabled = true;
      btn.dataset.idle = btn.textContent;
      btn.innerHTML = `<span class="spinner"></span>${{text}}`;
    }}
    function accBtnReset(btn) {{
      if (!btn) return;
      btn.disabled = false;
      btn.textContent = btn.dataset.idle || btn.textContent;
    }}
    async function doStart() {{
      const btn = event?.currentTarget || null;
      accBtnLoad(btn, "启动中…");
      try {{
        await api(`/api/accounts/${{encodeURIComponent(accountId)}}/start`, {{ method: "POST" }});
        await loadAccount();
        await pollAccQrcode(true);
        await pollAccLogs();
        notify("启动成功", "ok");
      }} catch (e) {{
        notify(e.message || e, "err");
      }} finally {{ accBtnReset(btn); }}
    }}
    async function doStop() {{
      const btn = event?.currentTarget || null;
      accBtnLoad(btn, "停止中…");
      try {{
        await api(`/api/accounts/${{encodeURIComponent(accountId)}}/stop`, {{ method: "POST" }});
        await loadAccount();
        notify("停止成功", "warn");
      }} catch (e) {{
        notify(e.message || e, "err");
      }} finally {{ accBtnReset(btn); }}
    }}
    async function doRestart() {{
      const btn = event?.currentTarget || null;
      accBtnLoad(btn, "重启中…");
      try {{
        await api(`/api/accounts/${{encodeURIComponent(accountId)}}/restart`, {{ method: "POST" }});
        await loadAccount();
        await pollAccQrcode(true);
        await pollAccLogs();
        notify("重启成功", "ok");
      }} catch (e) {{
        notify(e.message || e, "err");
      }} finally {{ accBtnReset(btn); }}
    }}
    async function doDelete() {{
      if (!confirm("确定删除该账号？")) return;
      const btn = event?.currentTarget || null;
      accBtnLoad(btn, "删除中…");
      try {{
        await api(`/api/accounts/${{encodeURIComponent(accountId)}}`, {{ method: "DELETE" }});
        location.href = document.getElementById("backDash").href;
      }} catch (e) {{
        notify(e.message || e, "err");
      }} finally {{
        accBtnReset(btn);
      }}
    }}
    accNbWireRunlogUi();
    (function init() {{
{token_sync_js}
      const u = new URL(location.href);
      const tabn = (u.searchParams.get("tab") || "overview").toLowerCase();
      tab(["overview","settings","configs"].includes(tabn) ? tabn : "overview");
    }})();
    loadHints().catch(() => {{}});
    bootAccountOverview();
    setInterval(() => {{
      if (document.hidden || activeTab !== "overview") return;
      loadAccount({{ brief: true }}).catch(() => {{}});
    }}, 10000);
    setInterval(() => {{
      if (document.hidden || activeTab !== "overview") return;
      pollAccLogs();
    }}, 8000);
    setInterval(() => {{
      if (document.hidden || activeTab !== "overview") return;
      pollAccQrcode(false);
    }}, 8000);
  </script>
  <div id="pageOverlay" class="page-overlay">
    <div class="page-overlay-inner">
      <div class="page-overlay-spinner"></div>
      <div class="page-overlay-label" id="pageOverlayLabel">保存中…</div>
    </div>
  </div>
  <div id="statusbar" class="statusbar"></div>
</body>
</html>
"""
