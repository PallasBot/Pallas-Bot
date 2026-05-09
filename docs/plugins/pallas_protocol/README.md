# pallas_protocol

在 Bot 内管理 NapCat / SnowLuma：账号、启动方式、WebUI、OneBot 配置与 Linux Docker。

## 架构（代码）

| 模块 | 职责 |
|------|------|
| `service.py` | 账号 CRUD、进程/Docker 启停、runtime profile、API 用例 |
| `launch_manager.py` | 按平台与 runtime 填充 `command`/`args`/`program_dir` |
| `linux_docker.py` / `snowluma_docker.py` | 各协议 `docker run` 参数；共用 `docker_cli.py`（inspect/rm/stop、镜像仓库解析） |
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
| `PALLAS_PROTOCOL_ONEBOT_WS_URL` | 完整反向 WS（最高优先级） |
| `PALLAS_PROTOCOL_ONEBOT_WS_HOST` / `_PORT` / `_PATH` | 未设 URL 时拼接 WS |
| `PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST` | NapCat 容器访问宿主机 Bot（默认 `172.17.0.1`） |
| `PALLAS_PROTOCOL_AUTO_DOWNLOAD_RUNTIME` | 无本地运行时是否后台下载 |
| `PALLAS_PROTOCOL_PROGRAM_DIR` | 手动指定 NapCat 发行根 |
| `PALLAS_PROTOCOL_DOCKER_IMAGE` | NapCat 镜像（可被 profile 覆盖） |
| `PALLAS_PROTOCOL_SNOWLUMA_DOCKER_IMAGE` | SnowLuma 镜像（可被 profile 覆盖） |

鉴权与 Pallas 控制台共用会话（`data/pallas_console/auth_state.json`），不再从 `.env` 读控制台口令。

## Docker 与 WS

Linux 上 NapCat 以 **bridge** 跑容器时，容器内解析不到 compose 自定义主机名；写入 `onebot*.json` 的 WS 主机会替换为 `PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST`，或直接使用 `PALLAS_PROTOCOL_ONEBOT_WS_URL`。

## 数据路径

- 实例：`data/pallas_protocol/instances/<id>/`
- 全局 profile：`data/pallas_protocol/runtime_profile.json`
- NapCat 托管解压：`data/pallas_protocol/runtime_extract/napcat/`
- SnowLuma 托管解压：`data/pallas_protocol/runtime_extract/snowluma/`

完整字段见 [`src/plugins/pallas_protocol/config.py`](../../../src/plugins/pallas_protocol/config.py)。

实现见 [`src/plugins/pallas_protocol/`](../../../src/plugins/pallas_protocol/)（上表所列模块均在目录内）。
