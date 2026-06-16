# 安装官方扩展

本文只讲 **官方扩展 pip 包**（决斗、MAA 等）。  
站点自写插件请看 [安装插件 · local](install-plugins.md#二安装站点自有插件local)。

::: tip 和 core 的区别
- **core**：复读、帮助、控制台……随 `uv run nb run` 就有  
- **官方扩展**：单独 `uv sync --extra plugins-xxx`，**装完要重启 Bot**
:::

---

## WebUI 安装（一步步点）

1. 打开 `http://<主机>:8088/pallas/` 并登录  
2. 侧栏 **插件商店**  
3. 搜索或浏览卡片 → **一键安装**  
4. 有 **安装并重启** 就点它；否则装完后自己重启 Bot  

**如何确认成功**：

| 商店显示 | 含义 |
| --- | --- |
| 未安装 | 还没 pip 装 |
| 已安装待重启 | pip 有了，重启后才会加载 |
| 已加载 | 当前进程里已经在跑 |

---

## 命令行安装

在仓库根目录执行（任选一个包）：

```bash
uv sync --extra plugins-duel
uv sync --extra plugins-maa
uv sync --extra plugins-who-is-spy
```

或用封装命令：

```bash
uv run pallas ext install pallas-plugin-duel
```

**如何确认成功**：

```bash
uv run python -c "import pallas_plugin_duel"   # 以决斗包为例，无 ImportError 即可
```

然后 **重启 Bot**。

---

## 扩展包对照表

| pip 包 | `uv sync --extra` | 包含插件（示例） |
| --- | --- | --- |
| `pallas-plugin-duel` | `plugins-duel` | 决斗 |
| `pallas-plugin-who-is-spy` | `plugins-who-is-spy` | 谁是卧底 |
| `pallas-plugin-maa` | `plugins-maa` | MAA 远控 |
| `pallas-plugin-dream` | `plugins-dream` | 做梦 |
| `pallas-plugin-draw` | `plugins-draw` | 画画 |
| `pallas-plugin-ai-media` | `plugins-ai-media` | 唱歌、酒后聊天 |
| `pallas-plugin-protocol` | `plugins-protocol` | 协议端管理、上号 |
| `pallas-plugin-llm-chat` | `plugins-llm-chat` | （多为 core，以实际为准） |
| `pallas-plugin-bot-status` | `plugins-bot-status` | 在吗、报数 |
| `pallas-plugin-community-stats` | `plugins-community-stats` | 社区统计客户端 |

完整说明与口令：[插件手册](../plugins/README.md)。

---

## Docker 用户

官方 `pallasbot/pallas-bot` 镜像往往是 **精简 core**，没有 `uv` 在容器里现场装包。

常见做法：

1. **构建镜像时** 带上 extras，例如 `PALLAS_UV_EXTRAS=perf,pg,plugins-game`（见 [Docker 部署](../DockerDeployment.md)）  
2. **挂载** `local/plugins/` 放插件代码  
3. 在**有源码的开发机** `uv sync --extra ...` 后整目录部署  

---

## 卸载

**WebUI**：插件商店 → **卸载**（仅对 pip 安装的包）

**命令行**：

```bash
uv run pallas ext uninstall pallas-plugin-duel
```

卸载 pip **不会**删 `local/plugins/` 里的副本。  
无论装还是卸，改完后都要 **重启 Bot**。

---

▶ 下一步：[插件手册](../plugins/README.md) · [安装插件总览](install-plugins.md)
