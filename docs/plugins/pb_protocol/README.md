# pb_protocol（协议端管理）

> **官方扩展**：`pallas-plugin-protocol`（`uv sync --extra plugins-protocol`）

多账号 **NapCat / SnowLuma** 协议端：创建牛牛、启停实例、日志与 OneBot 反向 WebSocket 配置同步。与 Web 控制台共用浏览器登录（口令在 `data/pallas_console/`）。

## 入口

| 路径 | 说明 |
| --- | --- |
| `/protocol/console/` | 协议端管理页（维护者向） |
| Web 控制台 | 侧边栏可跳转协议端；多机部署时协议端由 **hub** 托管 |

无群内用户口令。

## 典型流程

1. 浏览器登录控制台或协议端页（首次启动口令见 Bot 日志）。
2. **创建实例**：选择 NapCat 或 SnowLuma，填写 QQ 与反向 WS 地址（指向 Bot 的 `PORT` 或分片 **worker** 端口）。
3. **启动 / 停止**：在实例列表操作；日志可在页内查看。
4. **多机分片**：各牛牛账号的 `ws_url` 应指向所属 worker；`run_sharded_bot.sh start` 会同步注册表与协议端配置。

Docker 下 NapCat 默认不在 Compose 网络内，反向 WS 主机勿盲目填 `pallasbot` 服务名；插件会按 `PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST` 解析。详见 [Docker 部署](../DockerDeployment.md) 与 [FAQ](../FAQ.md#部署排障)。

## 命令权限

无。

## 配置

常用项（完整见 [`config.py`](../../../src/plugins/pb_protocol/config.py)，WebUI **插件 → pb_protocol**）：

| 键 | 说明 |
| --- | --- |
| `pallas_protocol_enabled` | 是否加载协议端插件 |
| `pallas_protocol_webui_enabled` | 是否挂载协议端 Web |
| `pallas_protocol_instances_root` | 实例根目录，默认 `data/pallas_protocol/instances/` |
| `pallas_protocol_program_dir` | NapCat 程序根目录（可配合自动下载） |
| `pallas_protocol_docker_onebot_host` | Docker 下写入 OneBot 客户端的主机名/IP |

## 排障

| 现象 | 处理 |
| --- | --- |
| 账号无法启动 | 查实例日志、NapCat/SnowLuma 版本与 `program_dir` |
| Bot 不回复 | 确认反向 WS 已连上对应 hub/worker 端口 |
| 与控制台登不上 | 共用 `data/pallas_console/` 口令；遗忘见 [FAQ · 部署排障](../FAQ.md#部署排障) |
| Docker WS 连不上 | 见 [FAQ · 协议端反向 WebSocket](../FAQ.md#q-协议端管理里反向-websocket-要不要写成主机为-pallasbot与-compose-的-pallasbot-是什么关系) |

## 实现

[`src/plugins/pb_protocol/`](../../../src/plugins/pb_protocol/)
