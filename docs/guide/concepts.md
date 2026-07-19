# 牛是怎么拼起来的

Pallas-Bot 由四块组成，各自职责如下：

| 组件 | 职责 |
| --- | --- |
| **协议端** | 替 QQ 登录、收发消息（如 NapCat） |
| **Pallas-Bot** | 处理消息：复读、帮助、插件玩法等 |
| **数据库** | 存储语料、群配置、`bot_config` 等 |
| **Web 控制台** | 改配置、看日志、装插件（路径 `/pallas/`） |

## 通信路径

![通信路径：QQ ↔ 协议端 ↔ Pallas-Bot ↔ 数据库，Web 控制台与 Bot 同进程](/assets/concepts-topology.png)

- 协议端与 Pallas-Bot 通过 **OneBot WebSocket** 通信
- Web 控制台与协议端管理页由 **同一 Bot 进程** 提供，无需另起服务
- 日常改插件配置：控制台保存即可；装/卸官方扩展需重启 Bot
- 端口、超管、数据库连接写在 `config/pallas.toml`；插件项写入 `data/pallas_config/webui.json`

▶ [快速开始](/guide/quickstart)
