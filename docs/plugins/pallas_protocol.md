# pallas_protocol

`pallas_protocol` 是 Pallas-Bot 的协议端管理插件，用于在 Bot 内管理 NapCat 运行时、多账号实例与 Web 控制页。

## 功能概览

- 在管理页维护协议端实例（创建、启动、停止、日志查看等）。
- 按账号保存运行数据到 `data/pallas_protocol/instances/<account_id>/`。
- 支持按平台下载/发现运行时，并可选 Linux Docker 运行模式。
- 对外提供管理页与 API，挂载路径默认为 `/protocol/<implementation>`。

## 常用环境变量（建议放 `.env`）

以下是日常最常用、最值得显式配置的项：

- `PALLAS_PROTOCOL_ENABLED`：是否启用协议端插件（默认 `true`）。
- `PALLAS_PROTOCOL_WEBUI_ENABLED`：是否启用协议端 Web 管理页（默认 `true`）。
- `PALLAS_PROTOCOL_WEB_IMPLEMENTATION`：管理页第二路径段（默认空，回退到 `contract.DEFAULT_PROTOCOL_BACKEND`，通常为 `napcat`）。
- `PALLAS_PROTOCOL_WEBUI_PATH`：整段覆盖管理页挂载路径（为空时自动生成 `/protocol/<slug>`）。
- `PALLAS_PROTOCOL_TOKEN`：管理页/API 鉴权 token（对应 `X-Pallas-Protocol-Token` 或 `?token=`）。
- `PALLAS_PROTOCOL_PROGRAM_DIR`：运行时目录（不填则自动发现/可配合自动下载）。
- `PALLAS_PROTOCOL_ONEBOT_HOST` / `PALLAS_PROTOCOL_ONEBOT_PORT` / `PALLAS_PROTOCOL_ACCESS_TOKEN`：反向 WS 连接关键项。

## 反向 WS 配置优先级

`resolve_onebot_ws_settings` 的解析顺序如下：

1. 插件配置字段（`pallas_protocol_onebot_*`, `pallas_protocol_access_token`）
2. 对应环境变量（`PALLAS_PROTOCOL_ONEBOT_*`, `PALLAS_PROTOCOL_ACCESS_TOKEN`）
3. 全局变量回退（`HOST`/`PORT`/`ACCESS_TOKEN`/`ONEBOT_*`）

固定路径为：`ws://<host>:<port>/onebot/v11/ws`

## 全量配置参考

下列配置都定义在 `src/plugins/pallas_protocol/config.py`，按用途分组如下。

### 基础开关与路径

- `pallas_protocol_enabled`（`PALLAS_PROTOCOL_ENABLED`）
- `pallas_protocol_webui_enabled`（`PALLAS_PROTOCOL_WEBUI_ENABLED`）
- `pallas_protocol_web_implementation`（`PALLAS_PROTOCOL_WEB_IMPLEMENTATION`）
- `pallas_protocol_webui_path`（`PALLAS_PROTOCOL_WEBUI_PATH`）
- `pallas_protocol_token`（`PALLAS_PROTOCOL_TOKEN`）
- `pallas_protocol_bind_host`（`PALLAS_PROTOCOL_BIND_HOST`）

### 运行时命令与目录

- `pallas_protocol_default_command`（`PALLAS_PROTOCOL_DEFAULT_COMMAND`）
- `pallas_protocol_default_args`（`PALLAS_PROTOCOL_DEFAULT_ARGS`，列表，`.env` 中通常写 JSON 字符串，如 `["napcat.mjs"]`）
- `pallas_protocol_program_dir`（`PALLAS_PROTOCOL_PROGRAM_DIR`）
- `pallas_protocol_default_working_dir`（`PALLAS_PROTOCOL_DEFAULT_WORKING_DIR`）
- `pallas_protocol_shell_template_dir`（`PALLAS_PROTOCOL_SHELL_TEMPLATE_DIR`）
- `pallas_protocol_instances_root`（`PALLAS_PROTOCOL_INSTANCES_ROOT`）

### 日志与端口范围

- `pallas_protocol_max_log_lines`（`PALLAS_PROTOCOL_MAX_LOG_LINES`）
- `pallas_protocol_webui_port_min`（`PALLAS_PROTOCOL_WEBUI_PORT_MIN`）
- `pallas_protocol_webui_port_max`（`PALLAS_PROTOCOL_WEBUI_PORT_MAX`）

### 运行时下载

- `pallas_protocol_github_repo`（`PALLAS_PROTOCOL_GITHUB_REPO`，默认按平台：Linux 为 `NapNeko/NapCatAppImageBuild`，其余为 `NapNeko/NapCatQQ`）
- `pallas_protocol_release_tag`（`PALLAS_PROTOCOL_RELEASE_TAG`，空表示 latest）
- `pallas_protocol_release_asset`（`PALLAS_PROTOCOL_RELEASE_ASSET`，空表示按平台默认；Linux 默认 `QQ-x86_64.AppImage`/`QQ-aarch64.AppImage`）
- `pallas_protocol_auto_download_runtime`（`PALLAS_PROTOCOL_AUTO_DOWNLOAD_RUNTIME`）

### OneBot 连接

- `pallas_protocol_onebot_host`（`PALLAS_PROTOCOL_ONEBOT_HOST`）
- `pallas_protocol_onebot_port`（`PALLAS_PROTOCOL_ONEBOT_PORT`）
- `pallas_protocol_access_token`（`PALLAS_PROTOCOL_ACCESS_TOKEN`）
- `pallas_protocol_onebot_client_name`（`PALLAS_PROTOCOL_ONEBOT_CLIENT_NAME`）

### Linux Docker（可选）

- `pallas_protocol_linux_use_docker`（`PALLAS_PROTOCOL_LINUX_USE_DOCKER`）
- `pallas_protocol_linux_use_xvfb`（`PALLAS_PROTOCOL_LINUX_USE_XVFB`，Linux 非 Docker 默认 `true`）
- `pallas_protocol_linux_xvfb_command`（`PALLAS_PROTOCOL_LINUX_XVFB_COMMAND`，默认 `xvfb-run`）
- `pallas_protocol_linux_xvfb_args`（`PALLAS_PROTOCOL_LINUX_XVFB_ARGS`，默认 `["--auto-servernum","--server-args=-screen 0 1280x720x24"]`）
- `pallas_protocol_linux_appimage_args`（`PALLAS_PROTOCOL_LINUX_APPIMAGE_ARGS`，默认 `["--appimage-extract-and-run"]`）
- `pallas_protocol_docker_image`（`PALLAS_PROTOCOL_DOCKER_IMAGE`）
- `pallas_protocol_docker_onebot_host`（`PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST`）
- `pallas_protocol_docker_internal_webui_port`（`PALLAS_PROTOCOL_DOCKER_INTERNAL_WEBUI_PORT`）

## 排障建议

- 管理页打不开：先检查 `PALLAS_PROTOCOL_WEBUI_ENABLED`、挂载路径配置、Bot 启动日志中的 URL。
- WS 未连接：优先补齐 `PALLAS_PROTOCOL_ONEBOT_HOST/PORT`，确认 `ACCESS_TOKEN` 一致。
- 运行时未找到：配置 `PALLAS_PROTOCOL_PROGRAM_DIR`，或启用 `PALLAS_PROTOCOL_AUTO_DOWNLOAD_RUNTIME` 并检查网络。
