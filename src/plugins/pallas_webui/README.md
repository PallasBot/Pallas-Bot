# pallas_webui

Pallas 控制台插件，负责：

- 挂载前端静态资源（`data/pallas_webui/public`）
- 提供控制台 API（默认前缀 `/pallas/api`）
- 在缺少本地 dist 时，按配置自动下载并解压 WebUI 产物

## 访问路径

- 页面：`/pallas/`（可通过 `pallas_webui_http_base` 修改前缀）
- API：`/pallas/api/*`

## 静态资源来源

插件启动时会先检查：

- `data/pallas_webui/public/index.html` 是否存在

若不存在，则进入自动下载逻辑。

### 自动下载优先级

1. 如果配置了 `pallas_webui_dist_zip_url`，直接用该 URL 下载。
2. 如果 `pallas_webui_dist_zip_url` 为空：
   - 先通过 GitHub Releases API 列出资产（优先 `tag`，再回退 `latest`）
   - 优先匹配 `pallas_webui_dist_zip_asset`
   - 若未精确命中，则选择第一个 `.zip` 资产
   - 同时保留固定直链兜底（`tag -> latest`）
3. 候选 URL 会逐个尝试，直到成功；全部失败会记录完整错误列表。

这样做的原因：减少 `.env` 中硬编码完整下载链接带来的 404/版本切换维护成本。

## 主要配置项

- `pallas_webui_enabled`：是否启用插件
- `pallas_webui_http_base`：页面与 API 的 URL 基路径（默认 `/pallas`）
- `pallas_webui_cors`：是否开启 CORS（本地前后端分离调试常用）
- `pallas_webui_log_lines_max`：日志 API 单次最大返回行数
- `pallas_webui_api_token`：非空时，写操作需要 `X-Pallas-Token` 或 `?token=`

下载相关配置：

- `pallas_webui_dist_zip_url`：dist.zip 直链（留空则走自动解析）
- `pallas_webui_dist_zip_repo`：GitHub 仓库（默认 `PallasBot/Pallas-Bot-WebUI`）
- `pallas_webui_dist_zip_tag`：release tag（空表示 latest）
- `pallas_webui_dist_zip_asset`：资产名（默认 `dist.zip`）

## 推荐配置

### 推荐（自动跟随最新）

```env
PALLAS_WEBUI_DIST_ZIP_URL=
PALLAS_WEBUI_DIST_ZIP_REPO=PallasBot/Pallas-Bot-WebUI
PALLAS_WEBUI_DIST_ZIP_TAG=
PALLAS_WEBUI_DIST_ZIP_ASSET=dist.zip
```

### 固定某版本

```env
PALLAS_WEBUI_DIST_ZIP_URL=
PALLAS_WEBUI_DIST_ZIP_REPO=PallasBot/Pallas-Bot-WebUI
PALLAS_WEBUI_DIST_ZIP_TAG=v0.2.0
PALLAS_WEBUI_DIST_ZIP_ASSET=dist.zip
```
