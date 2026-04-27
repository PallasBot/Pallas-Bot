# ruff: noqa: E501
"""管理页 HTML（字符串模板 + 内嵌 CSS）。"""

from __future__ import annotations

import json
from html import escape as html_escape

from ..contract import resolve_public_mount_path

NAPCAT_SHELL_CSS = """
:root {
  --bg0: #f2f6fc;
  --bg1: #f7fbff;
  --card: #ffffff;
  --bd: rgba(22, 100, 196, 0.14);
  --txt: #1f2a44;
  --muted: #5c6e8f;
  --accent: #1664c4;
  --accent2: #5f97de;
  --ok: #22a06b;
  --warn: #d99a00;
  --err: #d84a4a;
  --radius: 14px;
  --font: ui-sans-serif, system-ui, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0; min-height: 100vh; font-family: var(--font);
  background: radial-gradient(1200px 600px at 10% -10%, rgba(22,100,196,0.10), transparent),
              radial-gradient(900px 500px at 100% 0%, rgba(95,151,222,0.08), transparent),
              var(--bg0);
  color: var(--txt);
}
body[data-theme="dark"] {
  --bg0: #070a0f;
  --bg1: #0d121c;
  --card: #121a28;
  --bd: rgba(148, 163, 184, 0.16);
  --txt: #e8edf7;
  --muted: #8b9bb8;
  --accent: #38bdf8;
  --accent2: #5fd1ff;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.shell { max-width: 1280px; margin: 0 auto; padding: 28px 20px 48px; }
.topbar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 14px 20px;
  margin-bottom: 28px;
}
.brand { font-size: 1.35rem; font-weight: 700; letter-spacing: 0.02em; }
.brand span { color: var(--accent); }
.pill {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 8px 14px; border-radius: 999px;
  background: var(--card); border: 1px solid var(--bd); font-size: 0.85rem; color: var(--muted);
}
.token-inline {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 6px 10px;
  border-radius: 10px;
  border: 1px solid var(--bd);
  background: color-mix(in oklab, var(--card) 92%, transparent);
}
.token-inline input { width: 180px; height: 40px; padding: 10px 12px; }
.drawer-backdrop {
  position: fixed; inset: 0; z-index: 140;
  background: rgba(15, 24, 40, 0.38);
  opacity: 0; pointer-events: none; transition: opacity .2s ease;
}
.drawer-backdrop.open { opacity: 1; pointer-events: auto; }
.drawer {
  position: fixed; top: 0; right: 0; z-index: 150;
  height: 100%; width: min(300px, 86vw);
  background: var(--card); border-left: 1px solid var(--bd);
  box-shadow: -12px 0 32px rgba(15, 35, 65, 0.14);
  transform: translateX(100%); transition: transform .26s ease;
  padding: 22px 18px; display: flex; flex-direction: column; gap: 10px;
}
.drawer.open { transform: translateX(0); }
.drawer h3 { margin: 0 0 6px; font-size: 1rem; color: var(--muted); font-weight: 700; }
.drawer a.nav-item {
  display: block; padding: 12px 14px; border-radius: 10px;
  color: var(--txt); font-weight: 600; border: 1px solid var(--bd); background: var(--bg1);
  text-decoration: none;
}
.drawer a.nav-item:hover { border-color: rgba(22,100,196,0.35); }
.btn-icon {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 10px 12px; min-width: 44px; min-height: 44px;
}
.btn-icon svg { display: block; flex-shrink: 0; }
.busy {
  opacity: .75;
  cursor: wait !important;
}
.section.loading, .card.loading {
  animation: shell-fade-up .22s ease both;
}
input, textarea, select {
  background: var(--bg1); border: 1px solid var(--bd); color: var(--txt);
  border-radius: 10px; padding: 10px 12px; font: inherit;
}
input:focus, textarea:focus { outline: 2px solid rgba(56,189,248,0.35); border-color: var(--accent); }
.btn {
  border: none; border-radius: 10px; padding: 10px 16px; font-weight: 600; cursor: pointer;
  font: inherit; background: linear-gradient(135deg, var(--accent), #2b78d6); color: #fff;
  transition: transform .16s ease, filter .16s ease, box-shadow .2s ease;
}
.btn.secondary { background: var(--card); color: var(--txt); border: 1px solid var(--bd); }
.btn.linkish {
  background: transparent;
  color: var(--muted);
  border: none;
  box-shadow: none;
  padding: 8px 10px;
}
.btn.linkish:hover:not(:disabled) {
  transform: none;
  filter: none;
  box-shadow: none;
  color: var(--accent);
}
.btn.danger { background: linear-gradient(135deg, #e86666, #d84a4a); color: #fff; }
.btn:disabled { opacity: 0.45; cursor: not-allowed; }
.btn:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.03); box-shadow: 0 8px 18px rgba(0,0,0,.22); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 16px; }
.card {
  background: var(--card); border: 1px solid var(--bd); border-radius: var(--radius);
  padding: 18px 18px 16px; display: flex; flex-direction: column; gap: 10px;
  box-shadow: 0 10px 24px rgba(15, 35, 65, 0.10);
  transition: transform .22s ease, border-color .22s ease, box-shadow .22s ease;
}
.card:hover { transform: translateY(-2px); border-color: rgba(22,100,196,0.32); box-shadow: 0 16px 30px rgba(15, 35, 65, 0.16); }
.card h3 { margin: 0; font-size: 1.05rem; }
.tag { font-size: 0.72rem; padding: 3px 8px; border-radius: 6px; font-weight: 600; }
.tag.ok { background: rgba(52,211,153,0.15); color: var(--ok); }
.tag.run { background: rgba(56,189,248,0.15); color: var(--accent); }
.tag.stop { background: rgba(148,163,184,0.2); color: var(--muted); }
.tag.bad { background: rgba(248,113,113,0.15); color: var(--err); }
.muted { color: var(--muted); font-size: 0.82rem; line-height: 1.45; }
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.78rem; word-break: break-all;
}
.section { margin-top: 32px; }
.section > h2 {
  font-size: 1.05rem; margin: 0 0 14px; color: var(--muted); font-weight: 600;
  letter-spacing: 0.04em; text-transform: uppercase;
}
.row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 12px; }
.kpi {
  background: var(--bg1); border: 1px solid var(--bd); border-radius: 10px; padding: 10px 12px;
}
.kpi .k { color: var(--muted); font-size: 0.75rem; }
.kpi .v { font-size: 1.05rem; font-weight: 700; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.toolbar { margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.toolbar .grow { flex: 1; min-width: 220px; }
.help-tip { font-size: 0.78rem; color: var(--muted); }
.view-toggle {
  display: inline-flex;
  border: 1px solid var(--bd);
  border-radius: 10px;
  overflow: hidden;
  background: var(--card);
}
.view-toggle .btn {
  border-radius: 0;
  border: none;
  padding: 9px 12px;
  background: transparent;
  color: var(--muted);
  box-shadow: none;
  transform: none;
}
.view-toggle .btn:hover { filter: none; box-shadow: none; transform: none; color: var(--txt); }
.view-toggle .btn.active {
  background: linear-gradient(135deg, var(--accent), #2b78d6);
  color: #fff;
}
.table-wrap {
  overflow: auto;
  border: 1px solid var(--bd);
  border-radius: 10px;
  background: var(--bg1);
}
table.acc-table { width: 100%; border-collapse: collapse; min-width: 760px; }
table.acc-table th, table.acc-table td { padding: 10px 12px; border-bottom: 1px solid var(--bd); text-align: left; }
table.acc-table th { color: var(--muted); font-size: 0.96rem; font-weight: 700; letter-spacing: 0; text-transform: none; }
table.acc-table td { font-size: 0.96rem; }
.statusbar {
  position: fixed; right: 16px; bottom: 16px; z-index: 99;
  display: flex; flex-direction: column; gap: 8px; max-width: min(460px, 92vw);
}
.toast {
  background: var(--card); border: 1px solid var(--bd); color: var(--txt);
  border-radius: 10px; padding: 10px 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.3);
  font-size: 13px;
}
.toast.ok { border-color: rgba(52,211,153,0.45); animation: toast-in .22s ease both, success-pulse .9s ease .15s; }
.toast.warn { border-color: rgba(251,191,36,0.45); }
.toast.err { border-color: rgba(248,113,113,0.5); }
@keyframes toast-in {
  from { opacity: 0; transform: translateY(8px) scale(.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.toast { animation: toast-in .22s ease both; }
@keyframes shell-fade-up {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.section, .topbar, .layout-acc { animation: shell-fade-up .28s ease both; }
@keyframes spin { to { transform: rotate(360deg); } }
.spinner {
  display: inline-block; width: 13px; height: 13px;
  border: 2px solid rgba(255,255,255,0.35);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin .65s linear infinite;
  vertical-align: middle; margin-right: 5px;
}
.btn.secondary .spinner { border-color: rgba(100,120,160,0.22); border-top-color: var(--muted); }
@keyframes success-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(34,160,107,0.5); }
  60%  { box-shadow: 0 0 0 8px rgba(34,160,107,0); }
  100% { box-shadow: 0 0 0 0 rgba(34,160,107,0); }
}
.page-overlay {
  position: fixed; inset: 0; z-index: 9000;
  background: rgba(7, 14, 26, 0.55);
  backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center;
  opacity: 0; pointer-events: none;
  transition: opacity .2s ease;
}
.page-overlay.visible { opacity: 1; pointer-events: auto; }
.page-overlay-inner {
  display: flex; flex-direction: column; align-items: center; gap: 16px;
  background: var(--card); border: 1px solid var(--bd); border-radius: var(--radius);
  padding: 32px 40px; box-shadow: 0 20px 48px rgba(0,0,0,0.35);
}
.page-overlay-spinner {
  width: 36px; height: 36px;
  border: 3px solid rgba(56,189,248,0.25);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin .7s linear infinite;
}
.page-overlay-label { font-size: 0.95rem; font-weight: 600; color: var(--txt); }
pre.logs {
  background: #f3f8ff; color: #24324a; padding: 14px; border-radius: var(--radius);
  border: 1px solid var(--bd); max-height: min(68vh, 560px); overflow: auto; font-size: 12px; line-height: 1.45;
}
/* 协议端控制台里的 Unicode 块字符二维码需等宽 + 行高 1，否则格子对不齐无法扫 */
pre.logs.logs-protocol {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Courier New", monospace;
  line-height: 1;
  letter-spacing: 0;
  font-size: 11px;
  word-break: normal;
  overflow-wrap: normal;
}
body[data-theme="dark"] pre.logs {
  background: #0f1624;
  color: #dbe7ff;
}
body[data-theme="dark"] pre.logs.logs-protocol {
  color: #e8eefc;
}
.layout-acc { display: grid; grid-template-columns: clamp(180px, 22vw, 240px) minmax(0, 1fr); gap: 22px; align-items: start; }
.acc-main {
  min-width: 0;
  width: 100%;
  max-width: 980px;
}
@media (max-width: 860px) {
  .layout-acc { grid-template-columns: 1fr; gap: 12px; }
  .acc-main { max-width: none; }
  .side {
    position: static;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(138px, 1fr));
    gap: 8px;
    padding: 10px;
  }
  .side a {
    margin: 0;
    text-align: center;
    padding: 10px 8px;
  }
  .row {
    gap: 8px;
  }
}
.side {
  position: sticky; top: 18px;
  background: var(--card); border: 1px solid var(--bd); border-radius: var(--radius); padding: 12px;
}
.side a {
  display: block; padding: 10px 12px; border-radius: 10px; color: var(--muted); font-weight: 600; font-size: 0.92rem;
}
.side a:hover { background: var(--bg1); color: var(--txt); text-decoration: none; }
.side a.active { background: rgba(56,189,248,0.12); color: var(--accent); }
.panel { display: none; }
.panel.active { display: block; width: 100%; }
.panel > .card {
  width: 100%;
}
.field label { display: block; font-size: 0.78rem; color: var(--muted); margin-bottom: 6px; font-weight: 600; }
.field { margin-bottom: 14px; }
.field input, .field textarea { width: 100%; }
textarea.cfg { min-height: 220px; }
#onebotHint, #setMsg, #cfgMsg { margin: 2px 0 8px; }
"""


def _render_common_api_js() -> str:
    return """
    async function api(path, options = {}) {
      const token = (document.getElementById("token")?.value || "").trim();
      const headers = options.headers || {};
      if (token) headers["X-Pallas-Protocol-Token"] = token;
      const joiner = path.includes("?") ? "&" : "?";
      const tokenPart = token ? `${joiner}token=${encodeURIComponent(token)}` : "";
      const res = await fetch(`${basePath}${path}${tokenPart}`, { ...options, headers });
      if (!res.ok) throw new Error((await res.text()) || res.status);
      return res.json();
    }
"""


def _render_hidden_token_sync_js(back_button_id: str = "backDash") -> str:
    back_id_js = json.dumps(back_button_id)
    return f"""
    (function initTokenSync() {{
      const u = new URL(location.href);
      const fromQs = (u.searchParams.get("token") || "").trim();
      const fromLs = (localStorage.getItem("pallas_protocol_token") || "").trim();
      const t = fromQs || fromLs;
      const tokenEl = document.getElementById("token");
      if (tokenEl) tokenEl.value = t;
      const b = document.getElementById({back_id_js});
      if (b) b.href = t ? basePath + "?token=" + encodeURIComponent(t) : basePath;
    }})();
"""


def render_dashboard(base_path: str) -> str:
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    common_api_js = _render_common_api_js()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Pallas · 协议端仪表盘</title>
  <style>{NAPCAT_SHELL_CSS}</style>
</head>
<body data-base-path="{html_escape(path, quote=True)}">
  <div class="shell">
    <header class="topbar">
      <div class="brand">Pallas <span>协议端仪表盘</span></div>
      <div class="row" style="margin-left:auto;align-items:center;flex-wrap:wrap;gap:8px">
        <div class="token-inline">
          <input id="token" type="password" autocomplete="off" placeholder="Token" />
        </div>
        <a href="#" class="btn secondary" id="linkRuntime">更新/下载</a>
        <a href="#" class="btn secondary" id="linkImport">导入账号</a>
        <button class="btn secondary" id="btnTheme" type="button">切换深浅</button>
        <button class="btn secondary" id="btnRefresh" type="button" onclick="refreshAccounts()">刷新</button>
      </div>
    </header>

    <div class="section">
      <div class="row" style="justify-content:flex-start;align-items:center;margin-bottom:14px;gap:8px">
        <h2 style="margin:0">账号</h2>
        <a href="#" class="btn" id="linkNewAccount">+ 创建账号</a>
      </div>
      <div class="kpi-grid" id="kpis"></div>
      <div class="toolbar">
        <input id="search" class="grow" placeholder="筛选：输入 QQ / 实例名 / 账号 ID" oninput="renderAccounts()" />
        <div class="view-toggle" role="tablist" aria-label="视图切换">
          <button id="btnViewCard" class="btn active" type="button" onclick="setViewMode('card')">卡片视图</button>
          <button id="btnViewTable" class="btn" type="button" onclick="setViewMode('table')">表格视图</button>
        </div>
        <label class="pill" style="cursor:pointer">
          <input id="autoRefresh" type="checkbox" checked style="margin-right:6px" />
          自动刷新日志
        </label>
      </div>
      <div id="cards" class="grid"></div>
      <div id="tableWrap" class="table-wrap" style="display:none"></div>
    </div>

    <div class="section">
      <h2>日志输出</h2>
      <pre class="logs" id="nbLogs"></pre>
    </div>
  </div>
  <script>
    const basePath = {p};
    let accountRows = [];
    let viewMode = "card";
    function applyTheme(theme) {{
      const next = theme === "dark" ? "dark" : "light";
      document.body.setAttribute("data-theme", next);
      localStorage.setItem("pallas_protocol_theme", next);
      const b = document.getElementById("btnTheme");
      if (b) b.textContent = next === "dark" ? "切换浅色" : "切换深色";
    }}
    function setBusy(el, busy, idleText = "刷新", busyText = "刷新中...") {{
      if (!el) return;
      el.disabled = !!busy;
      el.classList.toggle("busy", !!busy);
      if (typeof el.textContent === "string") el.textContent = busy ? busyText : idleText;
    }}
    (function initPagePrefs() {{
      const t = localStorage.getItem("pallas_protocol_token") || "";
      const tokenEl = document.getElementById("token");
      tokenEl.value = t;
      tokenEl.addEventListener("input", () => {{
        localStorage.setItem("pallas_protocol_token", tokenEl.value || "");
      }});
      applyTheme(localStorage.getItem("pallas_protocol_theme") || "light");
      document.getElementById("btnTheme").addEventListener("click", () => {{
        const now = document.body.getAttribute("data-theme") === "dark" ? "dark" : "light";
        applyTheme(now === "dark" ? "light" : "dark");
      }});
    }})();
    function notify(msg, level = "ok") {{
      const host = document.getElementById("statusbar");
      const el = document.createElement("div");
      el.className = `toast ${{level}}`;
      el.textContent = String(msg || "");
      host.appendChild(el);
      setTimeout(() => el.remove(), 4200);
    }}
{common_api_js}
    document.getElementById("linkNewAccount").addEventListener("click", (e) => {{
      e.preventDefault();
      const t = document.getElementById("token").value.trim();
      location.href = `${{basePath}}/new${{t ? "?token=" + encodeURIComponent(t) : ""}}`;
    }});
    document.getElementById("linkRuntime").addEventListener("click", (e) => {{
      e.preventDefault();
      const t = document.getElementById("token").value.trim();
      location.href = `${{basePath}}/runtime${{t ? "?token=" + encodeURIComponent(t) : ""}}`;
    }});
    document.getElementById("linkImport").addEventListener("click", (e) => {{
      e.preventDefault();
      const t = document.getElementById("token").value.trim();
      location.href = `${{basePath}}/import${{t ? "?token=" + encodeURIComponent(t) : ""}}`;
    }});
    function openAccount(id) {{
      const token = document.getElementById("token").value.trim();
      const q = new URLSearchParams();
      if (token) q.set("token", token);
      const qs = q.toString();
      location.href = `${{basePath}}/account/${{encodeURIComponent(id)}}${{qs ? "?" + qs : ""}}`;
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
      const q = (document.getElementById("search").value || "").trim().toLowerCase();
      const mode = viewMode || "card";
      const rows = !q ? accountRows : accountRows.filter((a) => {{
        return String(a.id || "").toLowerCase().includes(q)
          || String(a.qq || "").toLowerCase().includes(q)
          || String(a.display_name || "").toLowerCase().includes(q);
      }});
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
          return `<tr>
            <td>${{a.display_name || a.qq || a.id}}</td>
            <td>${{a.qq || a.id}}</td>
            <td>${{a.runtime_version || "未知"}}</td>
            <td><span class="tag ${{cls}}">${{st}}</span></td>
            <td class="mono">${{a.native_webui_url ? `<a href="${{a.native_webui_url}}" target="_blank" rel="noopener">前往</a>` : "—"}}</td>
            <td>
              <div class="row">
                <button class="btn secondary" type="button" onclick="openAccount('${{a.id}}')">控制台</button>
                <button class="btn secondary" type="button" onclick="startAccount('${{a.id}}',this)">启动</button>
                <button class="btn secondary" type="button" onclick="stopAccount('${{a.id}}',this)">停止</button>
                <button class="btn secondary" type="button" onclick="restartAccount('${{a.id}}',this)">重启</button>
              </div>
            </td>
          </tr>`;
        }}).join("");
        tw.innerHTML = `<table class="acc-table"><thead><tr>
          <th>实例名</th><th>QQ号</th><th>版本</th><th>状态</th><th>内置 WebUI</th><th>操作</th>
        </tr></thead><tbody>${{body || `<tr><td colspan="6" class="muted">无匹配账号</td></tr>`}}</tbody></table>`;
        return;
      }}
      g.style.display = "grid";
      tw.style.display = "none";
      rows.forEach((a) => {{
        const st = a.connected ? "已连接" : (a.process_running ? "运行中" : (a.launch_ready ? "已停止" : "异常"));
        const cls = a.connected ? "ok" : (a.process_running ? "run" : (a.launch_ready ? "stop" : "bad"));
        const card = document.createElement("div");
        card.className = "card";
        const wu = a.native_webui_url || "";
        const wtok = (a.webui_token || "").replace(/</g, "");
        card.innerHTML = `
          <div class="row" style="justify-content:space-between;align-items:flex-start;gap:8px;padding-right:32px">
            <h3>${{a.display_name || a.id}} <span class="tag ${{cls}}">${{st}}</span></h3>
            <button class="btn secondary" type="button" onclick="openAccount('${{a.id}}')">控制台</button>
          </div>
          <div class="mono muted">QQ: ${{a.qq || a.id}}</div>
          <div class="mono muted">版本: ${{a.runtime_version || "未知"}}</div>
          ${{wu ? `<div class="mono"><a href="${{wu}}" target="_blank" rel="noopener">NapCat 内置 WebUI</a> · token ${{wtok}}</div>` : ""}}
          <div class="row" style="margin-top:8px">
            <button class="btn secondary" type="button" onclick="startAccount('${{a.id}}',this)">启动</button>
            <button class="btn secondary" type="button" onclick="stopAccount('${{a.id}}',this)">停止</button>
            <button class="btn secondary" type="button" onclick="restartAccount('${{a.id}}',this)">重启</button>
            <button class="btn danger" type="button" onclick="deleteAccount('${{a.id}}')">删除</button>
          </div>`;
        g.appendChild(card);
      }});
    }}
    function setViewMode(mode) {{
      viewMode = mode === "table" ? "table" : "card";
      document.getElementById("btnViewCard").classList.toggle("active", viewMode === "card");
      document.getElementById("btnViewTable").classList.toggle("active", viewMode === "table");
      renderAccounts();
    }}
    async function refreshAccounts(opts) {{
      const silent = !!(opts && opts.silent);
      const btn = document.getElementById("btnRefresh");
      if (!silent) setBusy(btn, true, "刷新", "刷新中...");
      try {{
        const data = await api("/api/accounts");
        accountRows = data.accounts || [];
        renderKpis(accountRows);
        renderAccounts();
        if (!silent) notify("已刷新账号列表", "ok");
      }} finally {{
        if (!silent) setBusy(btn, false, "刷新", "刷新中...");
      }}
    }}
    async function pollNbLogs() {{
      try {{
        const data = await api("/api/nonebot-logs?lines=800");
        const el = document.getElementById("nbLogs");
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
        el.textContent = (data.logs || []).join("\\n");
        if (atBottom) el.scrollTop = el.scrollHeight;
      }} catch (e) {{
        document.getElementById("nbLogs").textContent = String(e.message || e);
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
    async function deleteAccount(id) {{
      if (!confirm("确定删除 " + id + " ?")) return;
      try {{
        await api(`/api/accounts/${{id}}`, {{ method: "DELETE" }});
        await refreshAccounts({{ silent: true }});
        notify(`已删除 ${{id}}`, "warn");
      }} catch (e) {{
        notify(e.message || e, "err");
      }}
    }}
    refreshAccounts({{ silent: true }}).catch((e) => notify(e.message || e, "err"));
    pollNbLogs();
    setInterval(() => {{
      if (document.getElementById("autoRefresh").checked) {{
        pollNbLogs();
      }}
    }}, 2000);
  </script>
  <div id="statusbar" class="statusbar"></div>
</body>
</html>
"""


def render_import_page(base_path: str) -> str:
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    common_api_js = _render_common_api_js()
    token_sync_js = _render_hidden_token_sync_js("backDash")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>导入账号</title>
  <style>{NAPCAT_SHELL_CSS}
.result-row {{ display:flex; gap:8px; align-items:baseline; padding:6px 0; border-bottom:1px solid var(--bd); font-size:0.88rem; }}
.result-row:last-child {{ border-bottom:none; }}
.result-row .folder {{ font-weight:600; min-width:160px; }}
.result-row .detail {{ color:var(--muted); }}
  </style>
</head>
<body>
  <input type="hidden" id="token" value="" autocomplete="off" />
  <div class="shell">
    <header class="topbar">
      <div class="brand">Pallas <span>导入账号</span></div>
      <a class="btn secondary" id="backDash" href="{html_escape(path, quote=True)}" style="margin-left:auto;display:inline-flex;align-items:center">← 返回仪表盘</a>
    </header>

    <div class="card" style="max-width:42rem">
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

    <div id="resultSection" style="display:none;margin-top:24px">
      <div class="kpi-grid" id="resultKpis"></div>
      <div class="card" style="margin-top:12px;max-width:42rem">
        <h3 style="margin:0 0 10px">导入结果</h3>
        <div id="resultImported"></div>
        <div id="resultSkipped" style="margin-top:10px"></div>
        <div id="resultFailed" style="margin-top:10px"></div>
      </div>
    </div>
  </div>

  <script>
    const basePath = {p};
    document.body.setAttribute("data-theme", localStorage.getItem("pallas_protocol_theme") || "light");
{token_sync_js}
{common_api_js}

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


def render_new_account_page(base_path: str) -> str:
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    common_api_js = _render_common_api_js()
    token_sync_js = _render_hidden_token_sync_js("backDash")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>新建账号</title>
  <style>{NAPCAT_SHELL_CSS}</style>
</head>
<body data-base-path="{html_escape(path, quote=True)}">
  <input type="hidden" id="token" value="" autocomplete="off" />
  <div class="shell">
    <header class="topbar">
      <div class="brand">新建 <span>账号</span></div>
      <a class="btn secondary" id="backDash" href="{html_escape(path, quote=True)}" style="margin-left:auto;display:inline-flex;align-items:center">← 返回仪表盘</a>
    </header>
    <div class="card" style="max-width:28rem">
      <div class="field"><label>QQ 号</label>
        <input id="qq" inputmode="numeric" autocomplete="off" />
      </div>
      <div class="field"><label>显示昵称</label>
        <input id="display_name" autocomplete="off" placeholder="可选" />
      </div>
      <div class="field"><label>内置 WebUI 端口（可选）</label>
        <input id="webui_port" type="number" placeholder="留空则自动分配" />
      </div>
      <div class="field"><label>内置 WebUI token（可选）</label>
        <input id="webui_token" type="password" autocomplete="off" placeholder="留空则随机生成" />
      </div>
      <hr style="border:none;border-top:1px solid var(--bd);margin:6px 0 14px" />
      <h4 style="margin:0 0 12px;font-size:0.9rem;color:var(--muted);font-weight:700">WS 连接（协议端 → Bot，可选）</h4>
      <p class="muted" style="margin:0 0 12px">NapCat 主动连接 Bot 的地址。Bot 与协议端不同机部署时填写，留空则使用默认值 ws://127.0.0.1:8088/onebot/v11/ws。</p>
      <div class="field"><label>WS 连接地址</label>
        <input id="ws_url" placeholder="ws://bot-host:8088/onebot/v11/ws" autocomplete="off" />
      </div>
      <div class="field"><label>连接名（NapCat 侧显示）</label>
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
  <script>
    const basePath = {p};
    document.body.setAttribute("data-theme", localStorage.getItem("pallas_protocol_theme") || "light");
{token_sync_js}
{common_api_js}
    async function createAccount() {{
      try {{
        const wport = document.getElementById("webui_port").value.trim();
        const wtok = document.getElementById("webui_token").value.trim();
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
          ...(wport && !Number.isNaN(wn) ? {{ webui_port: wn }} : {{}}),
          ...(wtok ? {{ webui_token: wtok }} : {{}}),
          ...(wsUrl ? {{ ws_url: wsUrl }} : {{}}),
          ...(wsName ? {{ ws_name: wsName }} : {{}}),
          ...(wsTok ? {{ ws_token: wsTok }} : {{}}),
        }};
        if (!qq) throw new Error("请填写 QQ 号");
        await api("/api/accounts", {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify(body) }});
        const t = (document.getElementById("token").value || "").trim();
        location.href = t ? basePath + "?token=" + encodeURIComponent(t) : basePath;
      }} catch (e) {{ alert(e.message); }}
    }}
  </script>
</body>
</html>
"""


def render_runtime_page(base_path: str) -> str:
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    common_api_js = _render_common_api_js()
    token_sync_js = _render_hidden_token_sync_js("backDash")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>更新/下载</title>
  <style>{NAPCAT_SHELL_CSS}</style>
</head>
<body>
  <input type="hidden" id="token" value="" autocomplete="off" />
  <div class="shell">
    <header class="topbar">
      <div class="brand">Pallas <span>更新/下载</span></div>
      <a class="btn secondary" id="backDash" href="{html_escape(path, quote=True)}" style="margin-left:auto;display:inline-flex;align-items:center">← 返回仪表盘</a>
    </header>
    <div class="card">
      <p class="muted">
        此页面用于更新或下载协议端运行时；默认会自动从 release 资产中选择可用包。
        如需固定版本，请在配置中设置 <code>pallas_protocol_release_tag</code>。
      </p>
      <div class="kpi-grid">
        <div class="kpi"><div class="k">任务状态</div><div class="v" id="rtStatus">-</div></div>
        <div class="kpi"><div class="k">当前阶段</div><div class="v" id="rtStage">-</div></div>
        <div class="kpi"><div class="k">目标版本</div><div class="v" id="rtAsset" title="">-</div></div>
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
          <label>运行目录</label>
          <div class="mono" id="rtProgramDir">-</div>
        </div>
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn" id="btnUpdate" type="button" onclick="downloadRuntime()">立即更新</button>
        <button class="btn secondary" id="btnRescan" type="button" onclick="rescanRuntime()">刷新检测</button>
        <button class="btn secondary" id="btnRefreshRuntime" type="button" onclick="refreshRuntime()">刷新状态</button>
      </div>
      <div style="margin-top:18px;border:1px solid var(--bd);border-radius:var(--radius);padding:16px 18px;background:var(--bg1)">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px">
          <span style="font-size:0.95rem;font-weight:700;color:var(--txt)">选择版本</span>
          <button class="btn secondary" id="btnLoadReleases" type="button" onclick="loadReleases()" style="font-size:0.82rem;padding:7px 14px">加载版本列表</button>
        </div>
        <div id="releasesArea" style="display:none">
          <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px">
            <select id="releaseSelect" style="flex:1;min-width:200px;height:40px"></select>
            <button class="btn secondary" id="btnDownloadTag" type="button" onclick="downloadSelectedTag()">选择此版本</button>
          </div>
          <div id="releaseDetail" class="muted" style="font-size:0.78rem;min-height:1.4em"></div>
        </div>
        <p id="releasesPlaceholder" class="muted" style="margin:0;font-size:0.82rem">点击「加载版本列表」从 GitHub 获取可用版本。</p>
      </div>
      <details style="margin-top:14px">
        <summary class="muted" style="cursor:pointer">查看原始状态 JSON（排障用）</summary>
        <pre class="mono muted" id="runtimeStatus" style="max-height:min(70vh,720px);overflow:auto;margin-top:8px;font-size:12px"></pre>
      </details>
    </div>
  </div>
  <script>
    const basePath = {p};
    document.body.setAttribute("data-theme", localStorage.getItem("pallas_protocol_theme") || "light");
    function setBtnBusy(el, busy, idleText, busyText) {{
      if (!el) return;
      el.disabled = !!busy;
      el.textContent = busy ? busyText : idleText;
      el.classList.toggle("busy", !!busy);
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
{common_api_js}
    let runtimeRefreshing = false;
    async function refreshRuntime(opts = {{}}) {{
      const silent = !!opts.silent;
      if (runtimeRefreshing) return;
      runtimeRefreshing = true;
      if (!silent) {{
        setBtnBusy(document.getElementById("btnRefreshRuntime"), true, "刷新状态", "刷新中...");
      }}
      try {{
        const data = await api("/api/runtime");
        document.getElementById("runtimeStatus").textContent = JSON.stringify(data, null, 2);
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
        document.getElementById("runtimeStatus").textContent = String(e.message || e);
        setText("rtStatus", "失败");
        setText("rtStage", "错误");
        setText("rtMessage", String(e.message || e));
        setText("rtTime", new Date().toLocaleTimeString());
      }} finally {{
        if (!silent) {{
          setBtnBusy(document.getElementById("btnRefreshRuntime"), false, "刷新状态", "刷新中...");
        }}
        runtimeRefreshing = false;
      }}
    }}
    async function loadReleases() {{
      const btn = document.getElementById("btnLoadReleases");
      btn.disabled = true;
      btn.textContent = "加载中…";
      try {{
        const data = await api("/api/runtime/releases?limit=200");
        const releases = data.releases || [];
        const sel = document.getElementById("releaseSelect");
        sel.innerHTML = releases.map((r) => {{
          const label = r.tag_name + (r.prerelease ? " (pre)" : "") + (r.name && r.name !== r.tag_name ? " · " + r.name : "");
          return `<option value="${{r.tag_name}}">${{label}}</option>`;
        }}).join("");
        document.getElementById("releasesArea").style.display = "block";
        document.getElementById("releasesPlaceholder").style.display = "none";
        updateReleaseDetail(releases);
        sel.addEventListener("change", () => updateReleaseDetail(releases));
      }} catch (e) {{
        alert("加载 release 列表失败: " + (e.message || e));
      }} finally {{
        btn.disabled = false;
        btn.textContent = "刷新列表";
      }}
    }}
    function updateReleaseDetail(releases) {{
      const sel = document.getElementById("releaseSelect");
      const tag = sel.value;
      const r = releases.find((x) => x.tag_name === tag);
      const el = document.getElementById("releaseDetail");
      if (!r) {{ el.textContent = ""; return; }}
      const parts = [];
      if (r.published_at) parts.push("发布于 " + new Date(r.published_at).toLocaleDateString("zh-CN"));
      if (r.assets && r.assets.length) parts.push("资产: " + r.assets.map((a) => a.name).join(", "));
      el.textContent = parts.join(" · ");
    }}
    let pendingTag = null;
    function downloadSelectedTag() {{
      const sel = document.getElementById("releaseSelect");
      const tag = sel.value;
      if (!tag) {{ alert("请先选择版本"); return; }}
      pendingTag = tag;
      const detailEl = document.getElementById("releaseDetail");
      const assetHint = detailEl ? detailEl.textContent : "";
      setText("rtAsset", tag);
      setText("rtSource", assetHint ? "待下载: " + assetHint : "待下载: " + tag);
      setText("rtStatus", "待更新");
      setText("rtStage", "已选择");
      setText("rtMessage", "已选择版本 " + tag + "，点击「立即更新」开始下载");
      setText("rtTime", new Date().toLocaleTimeString());
      const btn = document.getElementById("btnDownloadTag");
      const prev = btn.textContent;
      btn.textContent = "✓ 已选择";
      setTimeout(() => {{ btn.textContent = prev; }}, 1500);
    }}
    async function downloadRuntime() {{
      setBtnBusy(document.getElementById("btnUpdate"), true, "立即更新", "更新中...");
      try {{
        const url = pendingTag
          ? "/api/runtime/download?tag=" + encodeURIComponent(pendingTag)
          : "/api/runtime/download";
        await api(url, {{ method: "POST" }});
        pendingTag = null;
        await refreshRuntime();
      }} catch (e) {{ alert(e.message); }}
      finally {{
        setBtnBusy(document.getElementById("btnUpdate"), false, "立即更新", "更新中...");
      }}
    }}
    async function rescanRuntime() {{
      setBtnBusy(document.getElementById("btnRescan"), true, "刷新检测", "检测中...");
      try {{
        await api("/api/runtime/rescan", {{ method: "POST" }});
        await refreshRuntime();
      }} catch (e) {{ alert(e.message); }}
      finally {{
        setBtnBusy(document.getElementById("btnRescan"), false, "刷新检测", "检测中...");
      }}
    }}
{token_sync_js}
    refreshRuntime({{ silent: true }});
    setInterval(() => refreshRuntime({{ silent: true }}), 1200);
  </script>
</body>
</html>
"""


def render_account_workspace(base_path: str, account_id: str) -> str:
    path = base_path.rstrip("/") or resolve_public_mount_path(path_override="", implementation_slug="")
    p = json.dumps(path)
    aid = json.dumps(account_id)
    aid_h = html_escape(account_id, quote=True)
    common_api_js = _render_common_api_js()
    token_sync_js = _render_hidden_token_sync_js("backDash")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>账号 {aid_h}</title>
  <style>{NAPCAT_SHELL_CSS}</style>
</head>
<body>
  <input type="hidden" id="token" value="" autocomplete="off" />
  <div class="shell">
    <header class="topbar">
      <div class="brand">账号 <span>{aid_h}</span></div>
      <a class="btn secondary" id="backDash" href="{html_escape(path, quote=True)}" style="margin-left:auto;display:inline-flex;align-items:center">← 返回仪表盘</a>
    </header>
    <div class="layout-acc">
      <nav class="side" id="nav">
        <a href="#" class="active" data-tab="overview">概览</a>
        <a href="#" data-tab="settings">设置</a>
        <a href="#" data-tab="configs">原始配置</a>
        <a href="#" id="accLinkRuntime">更新/下载</a>
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
          </div>
          <div class="card" style="margin-top:12px">
            <h3>协议端进程</h3>
            <pre class="logs logs-protocol" id="accLogs"></pre>
          </div>
          <div class="card" style="margin-top:12px">
            <h3>日志输出</h3>
            <p class="muted" style="margin-top:0">与仪表盘同源，为当前进程 Bot 主日志。</p>
            <pre class="logs" id="accNbLogs" style="max-height:min(32vh,360px)"></pre>
          </div>
        </section>
        <section class="panel" id="panel-settings">
          <div class="card">
            <h3>详细设置</h3>
            <p id="onebotHint" class="muted"></p>
            <p id="setMsg" class="muted"></p>
            <div class="field"><label>实例名</label><input id="display_name" /></div>
            <div class="field"><label>QQ（只读）</label><input id="qq" readonly /></div>
            <div class="field"><label>内置 WebUI 端口</label><input id="webui_port" type="number" /></div>
            <div class="field"><label>内置 WebUI token</label><input id="webui_token" autocomplete="off" /></div>
            <hr style="border:none;border-top:1px solid var(--bd);margin:6px 0 14px" />
            <h4 style="margin:0 0 12px;font-size:0.9rem;color:var(--muted);font-weight:700">WS 连接（协议端 → Bot）</h4>
            <p class="muted" style="margin:0 0 12px">NapCat 主动连接 Bot 的地址。Bot 与协议端不同机部署时在此填写 Bot 所在机器的地址，保存后重启协议端进程即可，无需重启 Bot。</p>
            <div class="field"><label>WS 连接地址</label>
              <input id="ws_url" placeholder="ws://bot-host:8088/onebot/v11/ws" autocomplete="off" />
            </div>
            <div class="field"><label>连接名（NapCat 侧显示）</label>
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
            <h3>配置所在根目录</h3>
            <p id="cfgMsg" class="muted"></p>
            <div class="field"><label>onebot</label><textarea class="cfg mono" id="tj_onebot"></textarea></div>
            <div class="field"><label>napcat</label><textarea class="cfg mono" id="tj_napcat"></textarea></div>
            <div class="field"><label>webui</label><textarea class="cfg mono" id="tj_webui"></textarea></div>
            <button class="btn" type="button" onclick="saveConfigs()">保存 JSON</button>
          </div>
        </section>
      </div>
    </div>
  </div>
  <script>
    const basePath = {p};
    const accountId = {aid};
    let accountProcessRunning = false;
    document.body.setAttribute("data-theme", localStorage.getItem("pallas_protocol_theme") || "light");
{common_api_js}
    let activeTab = "overview";
    function tab(name) {{
      activeTab = name;
      document.querySelectorAll(".panel").forEach((el) => el.classList.remove("active"));
      document.getElementById("panel-" + name).classList.add("active");
      document.querySelectorAll(".side a[data-tab]").forEach((a) => a.classList.toggle("active", a.dataset.tab === name));
      const t = document.getElementById("token").value.trim();
      const q = "tab=" + encodeURIComponent(name) + (t ? "&token=" + encodeURIComponent(t) : "");
      history.replaceState(null, "", `${{basePath}}/account/${{encodeURIComponent(accountId)}}?${{q}}`);
      if (name === "settings") loadHints();
    }}
    document.getElementById("nav").addEventListener("click", (e) => {{
      const a = e.target.closest("a[data-tab]");
      if (!a) return;
      e.preventDefault();
      tab(a.dataset.tab);
    }});
    document.getElementById("accLinkRuntime").addEventListener("click", (e) => {{
      e.preventDefault();
      const t = document.getElementById("token").value.trim();
      location.href = `${{basePath}}/runtime${{t ? "?token=" + encodeURIComponent(t) : ""}}`;
    }});
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
    async function loadAccount() {{
      const data = await api(`/api/accounts/${{encodeURIComponent(accountId)}}`);
      const a = data.account;
      accountProcessRunning = !!a.process_running;
      const ov = document.getElementById("ovBody");
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
      ov.innerHTML = `<div><strong>${{st}}</strong></div>
        <div class="muted" style="margin-top:8px">版本: ${{a.runtime_version || "未知"}}</div>
        ${{a.native_webui_url ? `<div style="margin-top:8px"><a href="${{a.native_webui_url}}" target="_blank" rel="noopener">打开原生 WebUI</a></div>` : ""}}
        <div class="muted" style="margin-top:8px">WORKDIR: ${{a.account_data_dir || ""}}</div>`;
      document.getElementById("display_name").value = a.display_name || "";
      document.getElementById("qq").value = a.qq || "";
      document.getElementById("webui_port").value = a.webui_port != null ? String(a.webui_port) : "";
      document.getElementById("webui_token").value = a.webui_token || "";
      document.getElementById("ws_url").value = a.ws_url || "";
      document.getElementById("ws_name").value = a.ws_name || "";
      document.getElementById("ws_token").value = a.ws_token || "";
    }}
    async function pollAccLogs() {{
      try {{
        const data = await api(`/api/accounts/${{encodeURIComponent(accountId)}}/logs?lines=900`);
        const el = document.getElementById("accLogs");
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
        el.textContent = (data.logs || []).join("\\n");
        if (atBottom) el.scrollTop = el.scrollHeight;
      }} catch (e) {{ document.getElementById("accLogs").textContent = String(e.message || e); }}
    }}
    async function pollAccNbLogs() {{
      try {{
        const data = await api("/api/nonebot-logs?lines=500");
        const el = document.getElementById("accNbLogs");
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
        el.textContent = (data.logs || []).join("\\n");
        if (atBottom) el.scrollTop = el.scrollHeight;
      }} catch (e) {{ document.getElementById("accNbLogs").textContent = String(e.message || e); }}
    }}
    async function loadJsonCfgs() {{
      const c = await api(`/api/accounts/${{encodeURIComponent(accountId)}}/configs`);
      document.getElementById("tj_onebot").value = JSON.stringify(c.onebot || {{}}, null, 2);
      document.getElementById("tj_napcat").value = JSON.stringify(c.napcat || {{}}, null, 2);
      document.getElementById("tj_webui").value = JSON.stringify(c.webui || {{}}, null, 2);
    }}
    async function saveSettings() {{
      const el = document.getElementById("setMsg");
      el.textContent = "";
      try {{
        const wport = document.getElementById("webui_port").value.trim();
        const wn = parseInt(wport, 10);
        const body = {{
          display_name: document.getElementById("display_name").value.trim(),
          webui_token: document.getElementById("webui_token").value.trim(),
          ws_url: document.getElementById("ws_url").value.trim(),
          ws_name: document.getElementById("ws_name").value.trim(),
          ws_token: document.getElementById("ws_token").value,
        }};
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
        hidePageLoading();
        el.textContent = put.restarted ? "已保存并已重启进程。" : (put.needs_restart ? "已保存，重启后生效。" : "已保存。");
        notify(el.textContent, "ok");
      }} catch (e) {{ hidePageLoading(); el.textContent = String(e.message || e); }}
    }}
    async function saveConfigs() {{
      const el = document.getElementById("cfgMsg");
      el.textContent = "";
      try {{
        const payload = {{
          onebot: JSON.parse(document.getElementById("tj_onebot").value || "{{}}"),
          napcat: JSON.parse(document.getElementById("tj_napcat").value || "{{}}"),
          webui: JSON.parse(document.getElementById("tj_webui").value || "{{}}"),
        }};
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
        hidePageLoading();
        el.textContent = cfgPut.restarted ? "已写入磁盘并已重启进程。" : (cfgPut.needs_restart ? "已写入磁盘，重启后生效。" : "已写入磁盘。");
        notify(el.textContent, "ok");
      }} catch (e) {{ hidePageLoading(); el.textContent = String(e.message || e); }}
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
        notify("重启成功", "ok");
      }} catch (e) {{
        notify(e.message || e, "err");
      }} finally {{ accBtnReset(btn); }}
    }}
    async function doDelete() {{
      if (!confirm("确定删除该账号？")) return;
      await api(`/api/accounts/${{encodeURIComponent(accountId)}}`, {{ method: "DELETE" }});
      location.href = document.getElementById("backDash").href;
    }}
    (function init() {{
{token_sync_js}
      const u = new URL(location.href);
      const tabn = (u.searchParams.get("tab") || "overview").toLowerCase();
      tab(["overview","settings","configs"].includes(tabn) ? tabn : "overview");
    }})();
    loadHints().catch(() => {{}});
    loadAccount().catch((e) => alert(e.message));
    loadJsonCfgs().catch(() => {{}});
    setInterval(() => {{
      if (activeTab === "overview") loadAccount().catch(() => {{}});
    }}, 4000);
    setInterval(() => {{
      if (activeTab === "overview") pollAccLogs();
    }}, 1800);
    setInterval(() => {{
      if (activeTab === "overview") pollAccNbLogs();
    }}, 2000);
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
