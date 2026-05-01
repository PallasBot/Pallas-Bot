# pallas_webui

`pallas_webui` 是 Pallas 控制台页面插件，负责两件事：

- 提供页面与 API 入口（默认 `/pallas/` 与 `/pallas/api/*`）
- 在本地没有前端静态文件时，自动下载并解压 WebUI 产物

## 你通常只需要配这些

```env
PALLAS_WEBUI_ENABLED=true
PALLAS_WEBUI_HTTP_BASE=/pallas
PALLAS_WEBUI_API_TOKEN=你的控制台口令
```

说明：

- `PALLAS_WEBUI_API_TOKEN`：必填，用于管理页/API 鉴权；插件加载时会将数字转为字符串，纯数字可不写引号（如 `1234`）；请求时请携带 `X-Pallas-Token` 或 `token` 参数
- 页面默认地址是 `/pallas/`，改了 `HTTP_BASE` 后地址会跟着变

## 前端静态资源

默认无需手动配置。启动时如果不存在 `data/pallas_webui/public/index.html`，插件会自动下载并解压 WebUI 产物。

如需手动部署，推荐下载 **本仓库（Pallas-Bot）对应版本的 Release 附件 `dist.zip`**（与当次 Bot 发版一并构建）；亦可使用 `Pallas-Bot-WebUI` 仓库 Release 中的 `dist.zip`。将 zip **解压到 `data/pallas_webui`**（内含 `public/` 目录，将得到 `data/pallas_webui/public/index.html` 等）。

## 下载高级配置（按需）

仅在你需要指定下载来源或固定版本时再配置：

- `PALLAS_WEBUI_DIST_ZIP_URL`：直链下载地址（优先级最高）
- `PALLAS_WEBUI_DIST_ZIP_REPO`：仓库（默认 `PallasBot/Pallas-Bot-WebUI`）
- `PALLAS_WEBUI_DIST_ZIP_TAG`：版本 tag（留空表示 latest）
- `PALLAS_WEBUI_DIST_ZIP_ASSET`：资产名（默认 `dist.zip`）

## 常见问题

- `PALLAS_WEBUI_API_TOKEN` 为纯数字时：`.env` 可不写引号（插件加载时会转为字符串）
- 页面打不开：先确认 `PALLAS_WEBUI_ENABLED=true`，以及访问路径是否与 `PALLAS_WEBUI_HTTP_BASE` 一致
- 接口提示未授权：检查请求头 `X-Pallas-Token` 或 URL 参数 `token`
- 升级前端后没变化：检查 `data/pallas_webui/public/` 是否被旧文件覆盖，必要时删除后重启触发重拉
