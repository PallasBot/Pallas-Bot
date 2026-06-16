# pallas-plugin-protocol

Pallas-Bot 4.0 官方扩展：**协议端管理**（NapCat / SnowLuma）与 **牛牛重新上号**（含分片 worker 转发）。

本包绑定三个 NoneBot 插件：

| 模块 | 插件 | 角色 |
| --- | --- | --- |
| `pallas_plugin_protocol` | 协议端管理 | hub / unified |
| `pallas_plugin_relogin_bot` | 重新上号、创建牛牛 | hub / unified |
| `pallas_plugin_relogin_forward` | 分片 worker 口令转发 | worker |

## 安装

需已安装 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot) **≥ 4.0**。

```bash
uv sync --extra plugins-protocol
```

未安装时 Web 控制台仍可打开；**协议端 / 实例** 页会提示安装本扩展。

开发联调：clone 本仓库后 `uv pip install -e .`。

## 多进程分片

- **hub** 加载 protocol + relogin_bot；**worker** 加载 relogin_forward。
- 各牛牛账号的 `ws_url` 指向所属 **worker** 端口；共享 **`data/`**。
- `run_sharded_bot.sh start` 会同步注册表与协议端配置。

详见：[多进程分片](https://PallasBot.github.io/Pallas-Bot-Docs/architecture/bot-process-sharding)

## 功能说明

### 协议端管理

多账号 NapCat / SnowLuma：创建牛牛、启停实例、日志与 OneBot 反向 WebSocket。与 Web 控制台共用浏览器登录。

| 入口 | 说明 |
| --- | --- |
| `/protocol/console/` | 协议端管理页（维护者向） |
| Web 控制台 | 侧边栏可跳转协议端 |

典型流程：登录控制台 → 创建实例 → 配置反向 WS → 启动。Docker 下注意 `PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST`。

常用配置（WebUI **插件 → pallas_protocol**）：

| 键 | 说明 |
| --- | --- |
| `pallas_protocol_enabled` | 是否加载协议端 |
| `pallas_protocol_webui_enabled` | 是否挂载协议端 Web |
| `pallas_protocol_instances_root` | 实例根目录 |
| `pallas_protocol_program_dir` | NapCat 程序目录 |

完整键：[`src/pallas_plugin_protocol/config.py`](src/pallas_plugin_protocol/config.py)

### 重新上号（relogin_bot）

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛重新上号 [QQ] | 私聊 | 号主重启本账号协议端 |
| 创建牛牛 … | 私聊 | 超管新建实例 |

| 命令 ID | 默认等级 |
| --- | --- |
| `relogin.relogin` | bot_moderator |
| `relogin.create` | superuser |

### 排障

| 现象 | 处理 |
| --- | --- |
| 账号无法启动 | 查实例日志、程序目录 |
| Bot 不回复 | 确认反向 WS 连上 hub/worker 端口 |
| 无二维码 | 查协议端日志与 `data/` 下二维码文件 |
| Docker WS 连不上 | 见文档站 FAQ · 协议端反向 WebSocket |

## 文档

| 说明 | 链接 |
| --- | --- |
| 协议端管理 | [文档站 · pallas_protocol](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/pallas_protocol) |
| 重新上号 | [文档站 · relogin_bot](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/relogin_bot) |
| 插件开发入门 | [develop/plugin/getting-started](https://PallasBot.github.io/Pallas-Bot-Docs/develop/plugin/getting-started) |

## 源码

- [`src/pallas_plugin_protocol/`](src/pallas_plugin_protocol/)
- [`src/pallas_plugin_relogin_bot/`](src/pallas_plugin_relogin_bot/)
- [`src/pallas_plugin_relogin_forward/`](src/pallas_plugin_relogin_forward/)
