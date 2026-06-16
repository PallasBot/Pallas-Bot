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

未安装时控制台仍可打开，**协议端 / 实例** 相关页会提示安装本扩展。

## 多进程分片

- **hub** 须安装本包（加载 protocol + relogin_bot）
- **worker** 须安装本包（加载 relogin_forward；玩法扩展另装）
- 共享同一路径 **`data/`**

详见：[多进程分片](https://PallasBot.github.io/Pallas-Bot-Docs/architecture/bot-process-sharding)

## 文档

| 说明 | 链接 |
| --- | --- |
| 协议端管理 | [文档站](https://PallasBot.github.io/Pallas-Bot-Docs/) |
| 插件开发入门 | [develop/plugin/getting-started](https://PallasBot.github.io/Pallas-Bot-Docs/develop/plugin/getting-started) |

## 源码

- [`src/pallas_plugin_protocol/`](src/pallas_plugin_protocol/)
- [`src/pallas_plugin_relogin_bot/`](src/pallas_plugin_relogin_bot/)
- [`src/pallas_plugin_relogin_forward/`](src/pallas_plugin_relogin_forward/)
