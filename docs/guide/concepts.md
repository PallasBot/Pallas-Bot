# 理解牛牛是怎么拼起来的

> **可跳过**：只想先跑起来请看 [五分钟跑起来](quickstart.md)。

```text
QQ 协议端（NapCat 等）  ←→  Pallas-Bot 本体  ←→  数据库（Mongo / PostgreSQL）
                                    │
                              Web 控制台 / 协议端页
```

| 部分 | 干什么 | 首次要不要管 |
| --- | --- | --- |
| **协议端** | 连 QQ、收发消息 | 要登录一次 QQ |
| **Pallas-Bot** | 复读、喝酒、帮助等 | `uv run nb run` 启动它 |
| **数据库** | 语料、群配置等 | 本机或 Docker 起一个库 |
| **Web 控制台** | 改配置、看日志 | `/pallas/`，用日志口令登录 |

## 配置写在哪

| 优先级 | 文件 | 写什么 |
| --- | --- | --- |
| 低 | `config/pallas.toml` | 端口、超管、数据库 |
| 中 | `.env`（可选） | nb/pip 插件 |
| **高** | `data/pallas_config/webui.json` | 控制台保存的插件项 |

日常改插件：**控制台保存即可**。见 [配置存储](../architecture/settings-storage.md)。

## 插件从哪来

默认只带 **核心插件**（复读、帮助、控制台等）。决斗、MAA、唱歌等为 **官方扩展**，在控制台「官方扩展」或 `pallas ext install` 安装。自写插件放 `local/plugins/`，见 [站点定制](../architecture/site-customization-and-updates.md)。

## 和 AI 的关系

聊天、唱歌、画画需另起 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)，在控制台填地址。不玩 AI 可不装。

## 下一步

- [五分钟跑起来](quickstart.md)
- [使用指南](../user/README.md)
- [多进程分片](../architecture/bot_process_sharding.md)
