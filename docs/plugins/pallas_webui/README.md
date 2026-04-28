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

- `PALLAS_WEBUI_API_TOKEN` 为空时，写操作不做 token 校验；建议生产环境设置
- 页面默认地址是 `/pallas/`，改了 `HTTP_BASE` 后地址会跟着变

## 前端静态资源从哪来

启动时先检查：

- `data/pallas_webui/public/index.html`

存在：直接使用本地文件  
不存在：触发自动下载

下载优先级：

1. 若设置了 `PALLAS_WEBUI_DIST_ZIP_URL`，优先直链下载
2. 否则走 GitHub Release 解析（仓库/tag/资产名）
3. 全部候选失败时，日志会输出失败详情

## 下载相关配置（按需）

- `PALLAS_WEBUI_DIST_ZIP_URL`：直链下载地址（最直接）
- `PALLAS_WEBUI_DIST_ZIP_REPO`：仓库（默认 `PallasBot/Pallas-Bot-WebUI`）
- `PALLAS_WEBUI_DIST_ZIP_TAG`：版本 tag（空为 latest）
- `PALLAS_WEBUI_DIST_ZIP_ASSET`：资产名（默认 `dist.zip`）

## 推荐配置示例

### 自动跟随最新

```env
PALLAS_WEBUI_DIST_ZIP_URL=
PALLAS_WEBUI_DIST_ZIP_REPO=PallasBot/Pallas-Bot-WebUI
PALLAS_WEBUI_DIST_ZIP_TAG=
PALLAS_WEBUI_DIST_ZIP_ASSET=dist.zip
```

### 固定某个版本

```env
PALLAS_WEBUI_DIST_ZIP_URL=
PALLAS_WEBUI_DIST_ZIP_REPO=PallasBot/Pallas-Bot-WebUI
PALLAS_WEBUI_DIST_ZIP_TAG=v0.2.0
PALLAS_WEBUI_DIST_ZIP_ASSET=dist.zip
```

## 常见问题

- 页面打不开：先确认 `PALLAS_WEBUI_ENABLED=true`，以及访问路径是否与 `PALLAS_WEBUI_HTTP_BASE` 一致
- 接口提示未授权：检查请求头 `X-Pallas-Token` 或 URL 参数 `token`
- 升级前端后没变化：检查 `data/pallas_webui/public/` 是否被旧文件覆盖，必要时删除后重启触发重拉
