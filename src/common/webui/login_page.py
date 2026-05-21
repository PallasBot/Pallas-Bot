"""Pallas-Bot 控制台与协议端管理共用的独立登录页 HTML（与 WebUI / 协议壳主题变量对齐）。"""

from __future__ import annotations

from datetime import datetime
from html import escape as html_escape
from typing import Literal
from urllib.parse import quote

LoginFaviconVariant = Literal["console", "protocol"]

_LOGIN_FAVICON_CONSOLE_PATH = (
    "M16 9a4.5 4.5 0 0 0-4.5 4.5V15h-2v10h13V15h-2v-1.5A4.5 4.5 0 0 0 16 9Z "
    "m0 2a2.5 2.5 0 0 1 2.5 2.5V15h-5v-1.5A2.5 2.5 0 0 1 16 11Z"
)
_LOGIN_FAVICON_CONSOLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#2563eb"/>'
    f'<path fill="#fff" d="{_LOGIN_FAVICON_CONSOLE_PATH}"/>'
    "</svg>"
)
_LOGIN_FAVICON_PROTOCOL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#0d9488"/>'
    '<path fill="#fff" d="M9 11h14v2H9Zm0 5h14v2H9Zm0 5h10v2H9Z"/>'
    "</svg>"
)


def _login_favicon_link_fragment(variant: LoginFaviconVariant) -> str:
    svg = _LOGIN_FAVICON_CONSOLE_SVG if variant == "console" else _LOGIN_FAVICON_PROTOCOL_SVG
    href = "data:image/svg+xml," + quote(svg, safe="")
    return f'  <link rel="icon" href="{html_escape(href, quote=True)}" type="image/svg+xml" />\n'


def shell_priest_png_href(public_base_path: str) -> str:
    """与协议壳 ``shell_favicon_link`` 同源：``_pallas_ui/pallas-priest.png``。"""
    p = (public_base_path or "").strip().rstrip("/")
    return f"{p}/_pallas_ui/pallas-priest.png" if p else "/_pallas_ui/pallas-priest.png"


def _login_theme_and_accent_js() -> str:
    """与 ``pages._pallas_theme_bridge_js`` / ``_shell_prefs_js`` 同源键，保证登录页与壳、WebUI 深浅色一致。"""
    return r"""
    (function () {
      const PALLAS_THEME_KEY = "pallas-webui-theme";
      const PALLAS_PROTOCOL_THEME_LEGACY = "pallas_protocol_theme";
      const PALLAS_THEME_MODE_KEY = "pallas-theme-mode";
      const __ACCENT = "pallas-accent-hex";
      function resolvePallasThemePreference() {
        try {
          const mode = localStorage.getItem(PALLAS_THEME_MODE_KEY);
          if (mode === "system") {
            try {
              return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
            } catch (e) { return "light"; }
          }
          if (mode === "dark" || mode === "light") return mode;
        } catch (e) {}
        try {
          const w = localStorage.getItem(PALLAS_THEME_KEY);
          if (w === "dark" || w === "light") return w;
        } catch (e) {}
        try {
          const p = localStorage.getItem(PALLAS_PROTOCOL_THEME_LEGACY);
          if (p === "dark" || p === "light") return p;
        } catch (e) {}
        try {
          if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark";
        } catch (e) {}
        return "light";
      }
      function applyPallasShellTheme(mode) {
        const next = mode === "dark" ? "dark" : "light";
        document.body.setAttribute("data-theme", next);
        document.documentElement.classList.toggle("dark", next === "dark");
      }
      function __shellRgb(hex) {
        const m = /^#?([a-fA-F\d]{2})([a-fA-F\d]{2})([a-fA-F\d]{2})$/.exec(String(hex || "").trim());
        if (!m) return [37, 99, 235];
        return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
      }
      function __shellToHex(r, g, b) {
        const c = function (x) {
          const t = Math.max(0, Math.min(255, x | 0)).toString(16);
          return t.length === 1 ? "0" + t : t;
        };
        return "#" + c(r) + c(g) + c(b);
      }
      function __shellRgba(hex, a) {
        const rgb = __shellRgb(hex);
        return "rgba(" + rgb[0] + "," + rgb[1] + "," + rgb[2] + "," + a + ")";
      }
      function __shellDarkenHex(hex, factor) {
        const rgb = __shellRgb(hex);
        return __shellToHex(Math.round(rgb[0] * factor), Math.round(rgb[1] * factor), Math.round(rgb[2] * factor));
      }
      function applyShellAccentFromStorage() {
        var hex = "#2563eb";
        try {
          var v = (localStorage.getItem(__ACCENT) || "").trim();
          if (/^#[0-9A-Fa-f]{6}$/.test(v)) hex = v;
        } catch (e) {}
        var strong = __shellDarkenHex(hex, 0.88);
        [document.documentElement, document.body].forEach(function (el) {
          if (!el) return;
          el.style.setProperty("--accent", hex);
          el.style.setProperty("--accent-strong", strong);
          el.style.setProperty("--accent-subtle", __shellRgba(hex, 0.14));
          el.style.setProperty("--accent-glow", __shellRgba(hex, 0.1));
        });
      }
      function initLoginChrome() {
        applyPallasShellTheme(resolvePallasThemePreference());
        applyShellAccentFromStorage();
      }
      window.__pallasLoginInitTheme = initLoginChrome;
      window.__pallasLoginToggleTheme = function () {
        var cur = document.body.getAttribute("data-theme") === "dark" ? "dark" : "light";
        var next = cur === "dark" ? "light" : "dark";
        try {
          localStorage.setItem(PALLAS_THEME_KEY, next);
          localStorage.setItem(PALLAS_PROTOCOL_THEME_LEGACY, next);
          localStorage.setItem(PALLAS_THEME_MODE_KEY, next);
        } catch (e) {}
        applyPallasShellTheme(next);
      };
    })();
"""


def render_pallas_login_page_html(
    *,
    document_title: str,
    surface_label: str,
    tagline: str,
    form_action: str,
    next_path: str,
    error_message: str = "",
    head_extra_html: str = "",
    footer_note: str = "",
    favicon_variant: LoginFaviconVariant | None = None,
    shell_brand_icon_base: str | None = None,
) -> str:
    """生成完整 HTML 文档字符串。``next_path`` 写入隐藏域，须已由调用方校验为站内路径。"""
    next_esc = html_escape(next_path, quote=True)
    action_esc = html_escape(form_action, quote=True)
    title_esc = html_escape(document_title, quote=True)
    label_esc = html_escape(surface_label, quote=True)
    tag_esc = html_escape(tagline, quote=True)
    err_block = ""
    if (error_message or "").strip():
        err_block = f'<p class="login-error" role="alert">{html_escape(error_message.strip())}</p>'
    y = datetime.now().year
    custom = (footer_note or "").strip()
    foot_line = f"{custom} · © {y} Pallas-Bot" if custom else f"© {y} Pallas-Bot"
    foot = f'<p class="login-foot">{html_escape(foot_line)}</p>'
    extra = head_extra_html or ""
    shell_base = (shell_brand_icon_base or "").strip()
    priest_href = (
        shell_priest_png_href(shell_brand_icon_base or "") if favicon_variant == "protocol" and shell_base else ""
    )
    if priest_href:
        favicon_link = f'  <link rel="icon" type="image/png" href="{html_escape(priest_href, quote=True)}" />\n'
    elif favicon_variant:
        favicon_link = _login_favicon_link_fragment(favicon_variant)
    else:
        favicon_link = ""
    if priest_href:
        logo_inner = (
            f'<img class="login-logo-img" src="{html_escape(priest_href, quote=True)}" alt="" decoding="async" />'
        )
        logo_wrap_class = "login-logo login-logo--img"
    else:
        logo_char = "▤" if favicon_variant == "protocol" else "◇"
        logo_inner = html_escape(logo_char, quote=True)
        logo_wrap_class = "login-logo"
    js_theme = _login_theme_and_accent_js()
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light dark" />
  <title>{title_esc}</title>
{favicon_link}{extra}  <style>
    :root {{
      --font-sans: "Pallas UI", "Noto Sans SC", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
        system-ui, -apple-system, "Segoe UI", sans-serif;
      --bg0: #f8fafc;
      --card: rgba(255, 255, 255, 0.94);
      --bd: rgba(15, 23, 42, 0.1);
      --txt: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --accent-strong: #1d4ed8;
      --accent-subtle: rgba(37, 99, 235, 0.14);
      --accent-glow: rgba(37, 99, 235, 0.1);
      --radius: 16px;
      --radius-xl: 22px;
      --glass-hi: rgba(255, 255, 255, 0.38);
    }}
    body[data-theme="dark"] {{
      --bg0: #080b12;
      --card: rgba(20, 26, 38, 0.92);
      --bd: rgba(255, 255, 255, 0.1);
      --txt: #f1f5f9;
      --muted: #94a3b8;
      --glass-hi: rgba(255, 255, 255, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: var(--font-sans);
      -webkit-font-smoothing: antialiased;
      color: var(--txt);
      background: var(--bg0);
    }}
    .login-wrap {{
      position: relative;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.25rem;
      overflow: hidden;
    }}
    .login-sky {{
      pointer-events: none;
      position: absolute;
      inset: 0;
      background: radial-gradient(80% 55% at 50% 0%, var(--accent-glow), transparent 70%);
    }}
    .login-blob {{
      pointer-events: none;
      position: absolute;
      border-radius: 9999px;
      filter: blur(56px);
      opacity: 0.42;
      background: var(--accent-subtle);
    }}
    .login-blob.a {{
      width: 18rem;
      height: 18rem;
      left: -4rem;
      top: 5rem;
      animation: pallasBlobA 9s ease-in-out infinite;
    }}
    .login-blob.b {{
      width: 20rem;
      height: 20rem;
      right: -3rem;
      bottom: 2rem;
      animation: pallasBlobB 11s ease-in-out infinite 0.5s;
    }}
    @keyframes pallasBlobA {{
      0%, 100% {{ transform: scale(1); opacity: 0.38; }}
      50% {{ transform: scale(1.08); opacity: 0.5; }}
    }}
    @keyframes pallasBlobB {{
      0%, 100% {{ transform: scale(1); opacity: 0.32; }}
      50% {{ transform: scale(1.1); opacity: 0.46; }}
    }}
    .login-theme-btn {{
      position: absolute;
      top: 1rem;
      right: 1rem;
      z-index: 20;
      border: 1px solid var(--bd);
      background: var(--card);
      color: var(--muted);
      border-radius: var(--radius);
      padding: 0.45rem 0.65rem;
      font: inherit;
      font-size: 0.8rem;
      cursor: pointer;
      backdrop-filter: blur(8px);
    }}
    .login-theme-btn:hover {{ color: var(--txt); border-color: color-mix(in srgb, var(--accent) 35%, var(--bd)); }}
    .login-card {{
      position: relative;
      z-index: 10;
      width: 100%;
      max-width: 26rem;
      border-radius: var(--radius-xl);
      border: 1px solid color-mix(in srgb, var(--accent) 12%, var(--bd));
      background: var(--card);
      box-shadow: 0 18px 48px rgba(15, 23, 42, 0.1);
      backdrop-filter: blur(14px);
      padding: 1.75rem 1.6rem 1.5rem;
    }}
    body[data-theme="dark"] .login-card {{
      box-shadow: 0 18px 48px rgba(0, 0, 0, 0.35);
    }}
    .login-head {{
      display: flex;
      align-items: center;
      gap: 0.85rem;
    }}
    .login-logo {{
      width: 3rem;
      height: 3rem;
      border-radius: 1rem;
      display: grid;
      place-items: center;
      background: color-mix(in srgb, var(--accent) 12%, transparent);
      border: 1px solid color-mix(in srgb, var(--accent) 22%, transparent);
      font-size: 1.35rem;
      line-height: 1;
    }}
    .login-logo.login-logo--img {{
      padding: 0.22rem;
    }}
    .login-logo-img {{
      width: 2.55rem;
      height: 2.55rem;
      object-fit: contain;
      display: block;
      border-radius: 0.72rem;
    }}
    .login-brand {{
      display: flex;
      flex-direction: column;
      gap: 0.15rem;
      min-width: 0;
    }}
    .login-brand-row {{
      display: flex;
      align-items: baseline;
      gap: 0.45rem;
      flex-wrap: wrap;
    }}
    .login-brand-name {{
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}
    .login-brand-badge {{
      font-size: 0.7rem;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .login-tagline {{
      margin: 0;
      font-size: 0.78rem;
      color: var(--muted);
      line-height: 1.45;
    }}
    .login-form {{
      margin-top: 1.35rem;
      display: flex;
      flex-direction: column;
      gap: 0.85rem;
    }}
    .login-field-wrap {{
      position: relative;
    }}
    .login-input {{
      width: 100%;
      height: 2.65rem;
      padding: 0 2.5rem 0 0.85rem;
      border-radius: var(--radius);
      border: 1px solid var(--bd);
      background: color-mix(in srgb, var(--bg0) 65%, var(--card));
      color: var(--txt);
      font: inherit;
      font-size: 0.9rem;
    }}
    body[data-theme="dark"] .login-input {{
      background: rgba(15, 23, 42, 0.45);
    }}
    .login-input:focus {{
      outline: none;
      border-color: color-mix(in srgb, var(--accent) 45%, var(--bd));
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
    }}
    .login-toggle-pwd {{
      position: absolute;
      right: 0.35rem;
      top: 50%;
      transform: translateY(-50%);
      border: none;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font-size: 0.75rem;
      padding: 0.35rem 0.5rem;
      border-radius: 0.45rem;
    }}
    .login-toggle-pwd:hover {{ color: var(--txt); background: color-mix(in srgb, var(--txt) 6%, transparent); }}
    .login-error {{
      margin: 0;
      padding: 0.5rem 0.65rem;
      border-radius: var(--radius);
      font-size: 0.78rem;
      text-align: center;
      color: #b91c1c;
      background: color-mix(in srgb, #ef4444 12%, transparent);
    }}
    body[data-theme="dark"] .login-error {{
      color: #fecaca;
      background: color-mix(in srgb, #ef4444 16%, transparent);
    }}
    .login-submit {{
      height: 2.65rem;
      border: 1px solid color-mix(in srgb, #fff 38%, var(--accent));
      border-radius: var(--radius);
      font: inherit;
      font-size: 0.92rem;
      font-weight: 600;
      color: #fff;
      cursor: pointer;
      background: linear-gradient(
        135deg,
        color-mix(in srgb, var(--accent) 88%, #fff) 0%,
        color-mix(in srgb, var(--accent-strong) 92%, #0f172a) 100%
      );
      box-shadow:
        inset 0 1px 0 var(--glass-hi),
        0 8px 22px color-mix(in srgb, var(--accent) 32%, transparent);
    }}
    .login-submit:disabled {{
      opacity: 0.55;
      cursor: not-allowed;
    }}
    .login-foot {{
      margin: 1.1rem 0 0;
      text-align: center;
      font-size: 0.68rem;
      color: var(--muted);
      line-height: 1.4;
    }}
  </style>
</head>
<body>
  <div class="login-wrap">
    <div class="login-sky" aria-hidden="true"></div>
    <div class="login-blob a" aria-hidden="true"></div>
    <div class="login-blob b" aria-hidden="true"></div>
    <button type="button" class="login-theme-btn" id="themeToggle" title="切换浅色/深色">主题</button>
    <section class="login-card" aria-labelledby="loginTitle">
      <header class="login-head">
        <div class="{logo_wrap_class}" aria-hidden="true">{logo_inner}</div>
        <div class="login-brand">
          <div class="login-brand-row">
            <span class="login-brand-name" id="loginTitle">Pallas-Bot</span>
            <span class="login-brand-badge">{label_esc}</span>
          </div>
          <p class="login-tagline">{tag_esc}</p>
        </div>
      </header>
      {err_block}
      <form class="login-form" id="loginForm" method="post" action="{action_esc}">
        <input type="hidden" name="next" value="{next_esc}" />
        <div class="login-field-wrap">
          <input
            class="login-input"
            id="tokenInput"
            name="token"
            type="password"
            placeholder="登录口令"
            autocomplete="current-password"
            required
          />
          <button type="button" class="login-toggle-pwd" id="togglePwd" aria-label="显示或隐藏口令">显示</button>
        </div>
        <button class="login-submit" type="submit" id="submitBtn">进入 →</button>
      </form>
      {foot}
    </section>
  </div>
  <script>
{js_theme}
    document.addEventListener("DOMContentLoaded", function () {{
      if (window.__pallasLoginInitTheme) window.__pallasLoginInitTheme();
      var input = document.getElementById("tokenInput");
      var btn = document.getElementById("togglePwd");
      if (btn && input) {{
        btn.addEventListener("click", function () {{
          var show = input.type === "password";
          input.type = show ? "text" : "password";
          btn.textContent = show ? "隐藏" : "显示";
        }});
      }}
      var tbtn = document.getElementById("themeToggle");
      if (tbtn && window.__pallasLoginToggleTheme) {{
        tbtn.addEventListener("click", function () {{ window.__pallasLoginToggleTheme(); }});
      }}
      var form = document.getElementById("loginForm");
      var sub = document.getElementById("submitBtn");
      if (form && sub) {{
        form.addEventListener("submit", function () {{
          sub.textContent = "验证中…";
          sub.disabled = true;
        }});
      }}
    }});
  </script>
</body>
</html>
"""
