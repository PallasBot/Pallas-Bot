# 为 Pallas-Bot 安装插件

::: tip
装完记得**重启**一次。群里发 **牛牛帮助**，新命令会出现在帮助图里。
:::

## 三类插件

| 类型 | 举例 | 要不要动手 |
| --- | --- | --- |
| **本体 core** | 复读、帮助、控制台 | 不用，自带 |
| **官方插件** | 决斗、MAA、谁是卧底 | 要单独装 |
| **社区 / 本地** | 第三方、自己写的 | 商店 git 装，或放 `local/plugins/` |

## 【推荐】控制台一键装

已经能打开控制台、账号有权限时：

1. 打开 `http://<主机>:8088/pallas/`
2. 侧栏进 **插件商店**
3. 点 **一键安装** → **安装并重启**（没有就装完手动重启）

| 商店显示 | 含义 |
| --- | --- |
| 未安装 | 还没装 |
| 已安装待重启 | 包有了，重启才加载 |
| 已加载 | 当前进程里在跑 |

::: details 没有「一键安装」？
常见原因：Docker 精简镜像、PATH 里没有 `uv`。改走 [命令行安装](#命令行安装)，或构建时带 extras（见 [Docker 部署](/deploy/docker)）。
:::

## 命令行安装

在 **Pallas-Bot 仓库根**（源码部署），或能跑 `uv` 的环境：

```bash
uv run pallas ext list
uv run pallas ext install pallas-plugin-duel --restart
```

一次预装常用官方插件：

```bash
uv sync --extra deploy-all
```

或按需：

```bash
uv run pallas ext install pallas-plugin-protocol
uv run pallas ext install pallas-plugin-duel
uv run pallas ext install pallas-plugin-who-is-spy
uv run pallas ext install pallas-plugin-maa
uv run pallas ext install pallas-plugin-ai-media
uv run pallas ext install pallas-plugin-draw
```

### 官方插件对照

| pip 包 | 包含（示例） |
| --- | --- |
| `pallas-plugin-duel` | 决斗 |
| `pallas-plugin-who-is-spy` | 谁是卧底 |
| `pallas-plugin-maa` | MAA 远控 |
| `pallas-plugin-dream` | 做梦 |
| `pallas-plugin-draw` | 画画 |
| `pallas-plugin-ai-media` | 唱歌、酒后聊天 |
| `pallas-plugin-protocol` | 协议端、上号 |
| `pallas-plugin-bot-status` | 在吗、报数 |

随时 @ 闲聊（`llm_chat`）和社区统计（`pb_stats`）已在 **core**，不用再装。

::: details Docker / extras 对照
| extra | 包含 |
| --- | --- |
| `plugins-protocol` | NapCat 协议端、重登 |
| `plugins-game` | 决斗 + 谁是卧底 |
| `plugins-maa` | MAA |
| `plugins-ai-media` | 唱歌 + 酒后 chat |
| `plugins-draw` | 画画 |
| `deploy-all` | 全官方插件 |

镜像构建见 [Docker 部署](/deploy/docker)。
:::

## 手动安装

### 控制台 · 社区插件

1. `/pallas/` → **插件商店** → **社区插件**
2. **安装**（或 **从 Git 安装**）→ 落到 `local/plugins/<ID>/`
3. 重启 Bot

建议在 `pallas.toml` 写上：

```toml
[bootstrap]
extra_plugin_dirs = ["local/plugins"]
```

**同名时 `local/plugins` 优先于官方 pip。**

::: details 收录与索引
向 [community-plugin-index](https://github.com/PallasBot/community-plugin-index) 提 PR。作者约定见 [写社区插件并上架](community-plugin-author.md)。更细说明见 [社区插件商店](community-plugin-store.md)。
:::

### 手动投放

```text
local/plugins/你的插件名/__init__.py
```

配好 `extra_plugin_dirs` 后重启即可。

## 卸载

- 控制台商店点 **卸载**，或：

```bash
uv run pallas ext uninstall pallas-plugin-duel --restart
```

卸载 pip **不会**删 `local/plugins/` 副本。
