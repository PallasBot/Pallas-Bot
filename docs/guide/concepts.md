# 理解牛牛是怎么拼起来的

::: tip 可跳过
只想先跑起来请直接看 [五分钟跑起来](quickstart.md)。  
本节帮助你在排错时知道「该查哪一块」。
:::

## 一条消息怎么走完

```text
QQ 用户发消息
    ↓
NapCat 等协议端（OneBot v11）
    ↓  WebSocket
Pallas-Bot 本体（NoneBot 插件们）
    ↓  读写
MongoDB 或 PostgreSQL
```

你在浏览器打开的 **Web 控制台**、**协议端管理页**，和上面是**同一个 Bot 进程**提供的，不是第三个独立服务。

---

## 四块分别干什么

| 块 | 干什么 | 你要不要先管 |
| --- | --- | --- |
| **协议端** | 替 QQ 登录、收发消息 | 要，至少扫码一次 |
| **Pallas-Bot** | 复读、喝酒、帮助、扩展玩法 | `uv run nb run` 启动它 |
| **数据库** | 存语料、群配置、用户数据 | 要先起一个 Mongo 或 PG |
| **Web 控制台** | 改配置、看日志、装扩展 | `/pallas/`，用启动日志里的口令 |

---

## 配置写在哪些文件

日常改插件开关：**在网页里点保存就行**，不用手改文件。

| 优先级 | 路径 | 写什么 |
| --- | --- | --- |
| 低 | `config/pallas.toml` | 端口、超管 QQ、连哪个数据库 |
| 中 | `.env`（可选） | 老式 nb/pip 插件项 |
| **高** | `data/pallas_config/webui.json` | **控制台保存的插件配置**（覆盖同名键） |

口令哈希在 `data/pallas_console/`，协议端实例数据在 `data/` 下各子目录。  
合并规则详解：[配置存储](../architecture/settings-storage.md)。

---

## 插件从哪来

```text
本体 core（默认就有）
    ├── repeater、help、drink …
官方扩展（要装 pip 包）
    ├── duel、maa、who_is_spy …
站点 local（你自己放代码）
    └── local/plugins/<名>/
```

- 装官方扩展：[安装插件](install-plugins.md)  
- 写自己的：[站点定制](../architecture/site-customization-and-updates.md)

---

## 和 AI 服务的关系

```text
Pallas-Bot  ←HTTP→  Pallas-Bot-AI（可选，另仓库）
```

唱歌、画画、部分智能对话要 **另起 AI 服务**，在控制台填地址。  
不玩 AI 可以不装，复读/喝酒/轮盘不受影响。见 [AI 扩展](ai.md)。

---

## 多只牛（进阶）

一台机器跑很多 QQ 号时，可用 **hub + worker 分片**，共用一份 `data/` 和 `pallas.toml`。  
见 [多进程分片](../architecture/bot_process_sharding.md)。

---

▶ [五分钟跑起来](quickstart.md) · [使用指南](../user/README.md) · [进阶介绍](advanced.md)
