# pallas_protocol

在 Bot 内管理 NapCat / SnowLuma：账号、启动方式、WebUI、OneBot 配置与 Linux Docker。

## 架构（代码）

| 模块 | 职责 |
|------|------|
| `service.py` | 账号 CRUD、进程/Docker 启停、runtime profile、API 用例 |
| `launch_manager.py` | 按平台与 runtime 填充 `command`/`args`/`program_dir` |
| `linux_docker.py` / `snowluma_docker.py` | 各协议 `docker run` 参数；共用 `docker_cli.py`（inspect/rm/stop、镜像仓库解析） |
| `docker_onebot_host.py` | 容器访问宿主机 Bot 时，反向 WebSocket 应写的主机名（`host.docker.internal` / `127.0.0.1` 等） |
| `backends/` | 协议后端抽象（NapCat / SnowLuma） |
| `config.py` | 环境变量与默认值（Pydantic） |
| `web/` | 管理页与路由 |

全局 Docker/AppImage 偏好写入 `data/pallas_protocol/runtime_profile.json`；多数项可在管理页「协议资产」保存，不必改 `.env`。

## `.env` 常用项

| 变量 | 说明 |
|------|------|
| `PALLAS_PROTOCOL_ENABLED` | 是否加载插件 |
| `PALLAS_PROTOCOL_WEBUI_ENABLED` | 是否挂载管理页 |
| `PALLAS_PROTOCOL_GITHUB_TOKEN` | 拉 Release 时限额（可选） |
| `PALLAS_PROTOCOL_ONEBOT_WS_URL` | 完整反向 WebSocket 地址（最高优先级；常见为明文 `ws`，见下节） |
| `PALLAS_PROTOCOL_ONEBOT_WS_HOST` / `_PORT` / `_PATH` | 未设 URL 时按主机、端口、路径拼接反向 WebSocket 地址 |
| `PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST` | NapCat/SnowLuma 容器访问宿主机 Bot；**留空或 `auto`**：`bridge` 在 **Linux** 下为 `docker0` 网卡 IPv4（ioctl）或回退 `172.17.0.1`（不用系统默认路由网关，避免写成局域网路由器）；**非 Linux** 常为 `host.docker.internal`；`host` 网络为 `127.0.0.1`；仍会在 `docker run` 加 `host.docker.internal:host-gateway`（Docker 20.10+）作辅助解析 |
| `PALLAS_PROTOCOL_AUTO_DOWNLOAD_RUNTIME` | 无本地运行时是否后台下载 |
| `PALLAS_PROTOCOL_PROGRAM_DIR` | 手动指定 NapCat 发行根 |
| `PALLAS_PROTOCOL_DOCKER_IMAGE` | NapCat 镜像（可被 profile 覆盖） |
| `PALLAS_PROTOCOL_SNOWLUMA_DOCKER_IMAGE` | SnowLuma 镜像（可被 profile 覆盖） |

鉴权与 Pallas-Bot 控制台共用会话（`data/pallas_console/auth_state.json`），不再从 `.env` 读控制台口令。

## Docker 与反向 WebSocket（OneBot）

OneBot v11 **反向 WebSocket** 在本项目文档与默认占位里多为 **明文 `ws` 方案**（与常见 NoneBot / NapCat 教程一致）；若你已在 Bot 与客户端两侧启用 TLS，再改用 **`wss://`** 并自行保证证书与端口。

Linux 上 NapCat 以 **bridge** 跑容器时，容器内往往解析不到 Compose 里的自定义主机名；写入 **`onebot*.json`** 时会把 **主机** 调整为解析后的 **`PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST`**（默认可留空，Linux 一般为**宿主机网关 IP**），也可在 `.env` 里直接写完整 **`PALLAS_PROTOCOL_ONEBOT_WS_URL`** 覆盖。

## 数据路径

- 实例：`data/pallas_protocol/instances/<id>/`
- 全局 profile：`data/pallas_protocol/runtime_profile.json`
- NapCat 托管解压：`data/pallas_protocol/runtime_extract/napcat/`
- SnowLuma 托管解压：`data/pallas_protocol/runtime_extract/snowluma/`

完整字段见 [`src/plugins/pallas_protocol/config.py`](../../../src/plugins/pallas_protocol/config.py)。

实现见 [`src/plugins/pallas_protocol/`](../../../src/plugins/pallas_protocol/)（上表所列模块均在目录内）。
