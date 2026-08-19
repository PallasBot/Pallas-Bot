# 为 Pallas-Bot 安装插件

> 目标：装好官方或社区插件，让牛牛获得新玩法
> 准备：Bot 已能正常运行，可打开控制台；安装社区插件前准备好 git 环境
> 完成之后：群里发送 **牛牛帮助** 能看到新命令

::: tip
安装完成后**重启 Bot**。重启后，在群里发送 **牛牛帮助**，确认新命令已出现在帮助图中。
:::

Bot 已能正常运行时，可以按插件来源选择安装方式：

| 类型 | 举例 | 要不要动手 |
| --- | --- | --- |
| **本体 core** | 复读、帮助、控制台 | 不用，自带 |
| **官方插件** | 决斗、MAA、谁是卧底 | 要单独装 |
| **社区 / 本地** | 第三方、自己写的 | 商店 git 装，或放 `local/plugins/` |

先安装官方插件时，建议使用控制台。安装社区插件或自己开发的插件，见后面的[社区和本地插件](#社区和本地插件)。

## 推荐：在控制台安装

如果可以打开控制台且账号有相应权限：

1. 打开 `http://<主机>:8088/pallas/`
2. 侧栏进 **插件商店**
3. 点 **一键安装** → **安装并重启**（没有就装完手动重启）

安装后，可通过商店状态确认进度：

| 商店显示 | 含义 |
| --- | --- |
| 未安装 | 还没装 |
| 已安装待重启 | 包有了，重启才加载 |
| 已加载 | 当前进程里在跑 |

::: details 找不到「一键安装」
常见原因是 Docker 精简镜像，或 PATH 中没有 `uv`。可改用[命令行安装](#命令行安装)；Docker 构建时也可带上 extras，见 [Docker 部署](/maintainer/deploy/docker)。
:::

## 命令行安装

在源码部署的 **Pallas-Bot 仓库根目录**，或任意可以运行 `uv` 的环境中，先查看可安装插件，再安装所需插件：

```bash
uv run pallas ext list
uv run pallas ext install pallas-plugin-duel --restart
```

`--restart` 会在安装完成后重启 Bot。若不带此参数，安装后需手动重启。

要一次预装常用官方插件：

```bash
uv sync --extra deploy-all
```

也可以按需要分别安装：

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
| `pallas-plugin-ai-media` | 牛牛唱歌 |
| `pallas-plugin-protocol` | 协议端、上号 |
| `pallas-plugin-bot-status` | 在吗、报数 |

随时 @ LLM 对话（`llm_chat`）和社区统计（`pb_stats`）已在 **core**，不用再装。

::: details 参考：Docker extras 对照
| extra | 包含 |
| --- | --- |
| `plugins-protocol` | NapCat 协议端、重登 |
| `plugins-game` | 决斗 + 谁是卧底 |
| `plugins-maa` | MAA |
| `plugins-ai-media` | 唱歌 |
| `plugins-draw` | 画画 |
| `deploy-all` | 全官方插件 |

镜像构建见 [Docker 部署](/maintainer/deploy/docker)。
:::

## 社区和本地插件

社区插件可从控制台安装；自行开发或手动取得的插件可投放到本地目录。两种方式安装后都需要重启 Bot。

### 从控制台安装社区插件

1. `/pallas/` → **插件商店** → **社区插件**
2. **安装**（或 **从 Git 安装**）→ 落到 `local/plugins/<ID>/`
3. 重启 Bot

建议在 `pallas.toml` 中配置：

```toml
[bootstrap]
extra_plugin_dirs = ["local/plugins"]
```

**同名时 `local/plugins` 优先于官方 pip。**

::: details 收录与索引
向 [community-plugin-index](https://github.com/PallasBot/community-plugin-index) 提 PR。作者约定见 [写社区插件并上架](community-plugin-author.md)。更细说明见 [社区插件商店](community-plugin-store.md)。
:::

### 手动投放本地插件

```text
local/plugins/你的插件名/__init__.py
```

配置好 `extra_plugin_dirs` 后重启 Bot。

若插件通过 PyPI 发布，先将依赖安装到已激活的虚拟环境，再仅将插件本体安装到本地目录：

```bash
source .venv/bin/activate
python -m pip install nonebot_plugin_example
python -m pip install --no-deps -t local/plugins nonebot_plugin_example
```

第一条会将插件运行依赖安装到 `.venv`；第二条的 `--no-deps` 不可省略，否则 pip 会将依赖也平铺到 `local/plugins/`，Bot 会把其中带有 `__init__.py` 的依赖目录误识别为插件。需要指定镜像时，在两条 `pip install` 命令后都追加相同的 `-i` 与 `--trusted-host` 参数。

## 卸载

可在控制台商店点 **卸载**，也可使用命令行：

```bash
uv run pallas ext uninstall pallas-plugin-duel --restart
```

卸载 pip 插件**不会**删除 `local/plugins/` 中的副本。
