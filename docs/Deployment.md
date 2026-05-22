# Pallas-Bot 3.0 部署教程

> 导航：[`README`](../README.md) · [`Docker 部署`](DockerDeployment.md) · [`多进程分片`](architecture/bot_process_sharding.md) · [`3.0 迁移`](Migration-v3.md) · [`FAQ`](FAQ.md)

快来部署属于你自己的牛牛吧 (｡･∀･)ﾉﾞ

## 看前提示

- 你需要一个额外的 QQ 小号，一台自己的 `电脑` 或 `服务器`，不推荐用大号进行部署
- 你自己部署的牛牛与其他牛牛数据并不互通，是一张白纸，需要从头调教
- **3.0** 起提供 **Web 控制台**（`/pallas/`）与 **协议端管理**（默认 `/protocol/console/`，由插件 `pallas_protocol` 提供），用于管理 NapCat 等协议端进程；数据后端可选 **MongoDB** 或 **PostgreSQL**
- 牛牛支持使用 `Docker Compose` 一键部署，可以参考 [Docker 部署](DockerDeployment.md)；仓库自带 Compose **默认不编排独立 NapCat**，QQ 协议端由 **协议端管理**（`/protocol/console/`）统一创建与连接
- **多牛生产环境**可选用 [多进程分片](architecture/bot_process_sharding.md)（hub + worker，共享 `data/`），见下文 [多进程分片（可选）](#多进程分片可选)
- 以下内容适用于将牛牛作为一个独立 `Bot` 部署。如果你想将牛牛功能作为一组 `plugin` 添加到现有 `Bot`，请参照 [作为插件部署](#作为插件部署) 一节

## 基本环境配置

1. 下载安装 [git](https://git-scm.com/downloads)，这是一个版本控制工具，可以用来方便的下载、更新牛牛的源码。
2. 下载牛牛源码

    在你想放数据的文件夹里，Shift + 鼠标右键，打开 Powershell 窗口，输入命令

    ```bash
    git clone https://github.com/PallasBot/Pallas-Bot.git
    ```

    受限于国内网络环境，请留意命令是否执行成功，若一直失败可以挂上代理。

3. 下载安装 [Python](https://www.python.org/downloads/)，推荐安装 3.12 以上版本，Windows 用户请确保安装时勾选了 “Add Python to PATH” 选项。

    如果你本地已有 Python 环境可以忽略本条，下方的 `uv` 会自动安装牛牛支持的 Python 版本。

4. 下载安装 [pipx](https://pypa.github.io/pipx/installation/)，用于安装 Python 应用（可执行文件）：

    ```bash
    python -m pip install --user pipx
    python -m pipx ensurepath
    ```

    为确保 `pipx` 路径生效，请关闭并重新打开 Powershell 窗口。

5. 使用 `pipx` 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/), 这是一个现代且高效的 Python 包和项目管理工具：

    ```bash
    pipx install uv
    ```

    如果你本地已有 uv 环境可以忽略本条，下方的 `uv` 会自动安装牛牛支持的 Python 版本。

## 项目环境配置

1. 安装依赖

    ```bash
    cd Pallas-Bot # 进入项目目录
    uv sync
    ```

    若 `.env` 中选用 **PostgreSQL** 作为数据后端，请安装 PG 相关依赖（可与下面 `perf` 组合）：

    ```bash
    uv sync --extra pg
    # 或同时启用分词加速：uv sync --extra perf --extra pg
    ```

2. （可选）使用 `jieba-next` 分词（`perf` 可选依赖）

    项目默认安装 `jieba`。加群较多、消息量大的用户可启用 **`perf`**，使用 `jieba-next` 提升分词速度（群较少可跳过）。

    ```bash
    uv sync --extra perf
    ```

    若安装失败，在 Windows 上可能需要额外安装 `Visual Studio`，Linux 上需要 `build-essential`。
    注：启用 `perf` 后，运行时会优先使用 `jieba-next`，否则回退到 `jieba`，无需改代码。

3. 准备数据库（`MongoDB` 或 `PostgreSQL`）

    - **MongoDB**（默认上手简单）
      - [Windows 平台安装 MongoDB](https://www.runoob.com/mongodb/mongodb-window-install.html)
      - [Linux 平台安装 MongoDB](https://www.runoob.com/mongodb/mongodb-linux-install.html)
    - **PostgreSQL**（3.0 支持；迁移见 [`3.0 迁移指南`](Migration-v3.md)）
      - [Windows 平台安装 PostgreSQL](https://www.postgresql.org/download/windows/)
      - [Linux 平台安装 PostgreSQL](https://www.postgresql.org/download/linux/)
      - 使用 PG 时务必已执行 `uv sync --extra pg`（见上一步）。

    只需保证数据库可连接并在 `.env` 中配置正确，库表等会由 `Pallas-Bot` 在启动时初始化。

4. 配置语音功能

    - 配置 FFmpeg：[安装 FFmpeg](https://napneko.github.io/config/advanced#%E5%AE%89%E8%A3%85-ffmpeg)

    Pallas-Bot 会在启动时自动检查并下载语音文件。

    手动下载（仅在自动下载失败时需要）：

    - 下载 [牛牛语音文件](https://huggingface.co/pallasbot/Pallas-Bot/blob/main/voices/Pallas.zip)，解压放到 `resource/voices/` 文件夹下，目录结构参考 [path_structure.txt](../resource/voices/path_structure.txt)

5. 连接 QQ 协议端（两种方式任选或按环境组合）

    **方式 A：3.0 协议端管理（推荐先了解）**

    启动 `Pallas-Bot` 后，在浏览器打开 **协议端管理页**（默认与 Bot 同机同端口）：

    - 地址：`http://<主机IP>:8088/protocol/console/`（若改了 `HOST`/`PORT` 或插件里自定义了 `PALLAS_PROTOCOL_WEBUI_PATH`，请按实际为准）
    - 管理页鉴权与 Pallas-Bot 控制台共用（浏览器登录，口令哈希在 `data/pallas_console/`）。可选：`PALLAS_PROTOCOL_ENABLED`、`PALLAS_PROTOCOL_WEBUI_ENABLED`（默认一般为开；可在控制台「插件」→ `pallas_protocol` 中调整）

    在页面内可完成 NapCat **运行模式**（如 Docker / AppImage / Shell）、**镜像或本地下载**、**实例创建与启停**、日志等；具体步骤与排障见 [`pallas_protocol` 插件说明](plugins/pallas_protocol/README.md)。

    **方式 B：自行安装 NapCat / 其他 OneBot 客户端（与常见 NoneBot 部署相同）**

    若你已在机器上单独安装了 `NapCat`，可继续用手动配 WS 的方式接入，无需强制使用方式 A。

    - 部署步骤参照 [NapCat](https://napneko.github.io/) 官方文档；Windows 可选用 [NapCat.Win.一键版本](https://napneko.github.io/guide/boot/Shell#napcat-win-%E4%B8%80%E9%94%AE%E7%89%88%E6%9C%AC)。
    - 运行 `NapCat` 后访问 `http://localhost:6099/webui`（默认 `token`：`napcat`），在 `网络配置` → `新建` → `WebSocket 客户端` 中启用，**URL** 填 **`ws://localhost:8088/onebot/v11/ws`**（明文 WebSocket；远程部署时把 `localhost` 换成 Bot 所在机器 IP）。
    - 其他客户端示例：[Lagrange.OneBot](https://lagrangedev.github.io/Lagrange.Doc/v1/Lagrange.OneBot/)、[AstralGocq](https://github.com/ProtocolScience/AstralGocq) 等，`WebSocket` 目标路径同上。

6. （可选）配置 `config/pallas.toml`

    复制 [`config/pallas.example.toml`](../config/pallas.example.toml) 为 **`config/pallas.toml`**（已 gitignore，勿提交密钥），填写 `[bootstrap]` 监听与数据库等。其余项建议在启动后于控制台 **「插件」「通用配置」** 中编辑（写入 `data/pallas_config/webui.json`），或查阅 [配置存储](architecture/settings-storage.md) 与 [插件文档索引](plugins/README.md)。从旧 `.env` 迁移：`uv run python tools/migrate_env_to_pallas.py`。

## 启动 Pallas-Bot

```bash
cd Pallas-Bot # 进入项目目录
uv run nb run        # 运行
```

**注意：请不要关闭这个命令行窗口！这会导致 `Pallas-Bot` 停止运行！**
**同样请不要关闭 `NapCat` 的命令行窗口！**
Linux 用户推荐使用 [Termux](https://termux.dev/) 或 [GNU Screen](https://zhuanlan.zhihu.com/p/405968623) 来保持 `Pallas-Bot` 和 QQ 客户端在后台运行，或者考虑使用 [Docker 部署](DockerDeployment.md)。

## 多进程分片（可选）

当同一台机器需要长期运行 **多只牛牛**（例如十余个 QQ 账号）且单进程出现卡顿、延迟堆积时，可启用 **hub + worker** 分片模式，而不是继续加大单进程负载。

- **默认**：`uv run nb run`（单进程），适合牛数量较少或初次部署。
- **分片**：1 个 **hub**（WebUI、协议端管理、注册表）+ 多个 **worker**（各接一部分牛牛的反向 WebSocket），**共用同一 `data/` 目录**与同一份 **`config/pallas.toml`**（数据库等全局配置一致）。
- **启动**：在仓库根目录执行 `./scripts/run_sharded_bot.sh start`（详见 [多进程分片架构说明](architecture/bot_process_sharding.md)）。
- **控制台**：仍只访问 hub 端口（默认 `http://<主机>:8088/pallas/`）；协议端管理也在 hub。
- **注意**：worker 需额外监听端口（默认从 8090 起）；协议端各账号的 WebSocket 会指向对应 worker，变更端口后须在协议端 **重启** 账号。使用 PostgreSQL 时请预留足够 `max_connections`。

从单进程切换到分片前请备份 `data/`。Docker 编排示例见 [Docker 部署 · 多进程分片](DockerDeployment.md#多进程分片可选)。

## 进程守护脚本

（可选）仓库提供 **`tools/scripts/bot_watchdog.py`**：按间隔请求 Web 控制台的 **`/pallas/api/health`**（需启用 **`pallas_webui`**），在进程连续无响应达到阈值后，**结束当前子进程并重新执行启动命令**，或（可选）在宿主机对指定容器执行 **`docker restart`**。适合「希望有一条常驻监护进程」而不只依赖手动重开终端的场景。

**HOST / PORT 从哪来**：与 Bot 一致——当前 shell 的**环境变量优先**；未 `export` 时，脚本会从 **`--workdir` 目录下的 `.env`**（遗留）或 **`config/pallas.toml` 的 `[bootstrap]`** 读取 **`HOST`、`PORT`、`ONEBOT_PORT`**。默认 `--workdir` 为仓库根。

**与「谁启动 Bot」配合**：

- **由守护脚本负责拉起 Bot**：在仓库根执行，**不要**加 `--no-spawn`（默认子进程为 `uv run nb run`，可用 `--start` 自定义整条命令）。
- **Bot 已由 systemd、screen、另一终端或 Docker Compose 启动**：必须加 **`--no-spawn`**，否则脚本会再拉起一条 Bot，**端口冲突**。
- **Bot 跑在 Docker 容器内、在宿主机上监护**：使用 **`--docker-container <容器名> --no-spawn`**（宿主机需已安装 `docker` CLI，且容器名与 `docker compose` 中一致）。

**常用命令**（均在项目根，且已 `uv sync`）：

```bash
# 由守护进程启动 Bot（HOST/PORT 来自环境或 ./.env）
uv run python tools/scripts/bot_watchdog.py

# Bot 已在跑：只探活、不重复启动
uv run python tools/scripts/bot_watchdog.py --no-spawn

# 失败时在宿主机重启 compose 中的 Bot 容器（示例名 pallasbot，按实际修改）
uv run python tools/scripts/bot_watchdog.py --docker-container pallasbot --no-spawn
```

生产环境可将上述命令写入 **systemd** `User=` 服务、`supervisor` 或 **`screen`/`tmux`** 会话，与 Bot 是否同机同用户按需调整。脚本首轮探活成功会打一条 **INFO**，之后仅在失败、恢复时继续输出日志；更多参数与边界说明见脚本顶部文档字符串或执行 **`uv run python tools/scripts/bot_watchdog.py --help`**。

## 访问 3.0 控制台与协议端管理

启动后可在浏览器访问（端口以 `.env` 中 `PORT` 为准，默认 `8088`）：

- **总控 / 数据与插件等**：`http://<主机IP>:8088/pallas/`（HTTP API 基址一般为 `http://<主机IP>:8088/pallas/api`）
- **协议端管理（NapCat 等）**：`http://<主机IP>:8088/protocol/console/`（与 `pallas_protocol` 插件默认挂载一致）

若修改了 `HOST` / `PORT` 或 `pallas_webui_http_base`、协议端自定义路径，请按实际 URL 访问。

- 控制台与协议端写操作需先登录（同源 Cookie 会话）；仅本机开发可在 `pallas_webui` 中开启 `pallas_webui_dev_mode`。
- 协议端管理页说明见 [`pallas_protocol` 说明](plugins/pallas_protocol/README.md)。

## 后续更新

部署方式不同，推荐做法也不同：

- **Docker / Compose（推荐生产）**：代码在镜像层，不涉及你本机上的 git 合并冲突。在 compose 目录执行 `docker compose pull`（或你编排里写的镜像拉取命令）后重建容器即可，详见 [Docker 部署](DockerDeployment.md)。
- **本机 git clone（开发或手动部署）**：在项目目录打开终端，拉取上游变更后重启 Bot。

```bash
git pull origin main --autostash
```

`--autostash` 会在拉取前临时 stash **未提交**的本地修改，拉完再尝试恢复；**不能**自动解决「你与上游改了同一处已跟踪文件」的合并冲突，此时需在本地手动 `merge`/`rebase` 解决后再拉。无人值守自动拉取时更稳妥的做法是使用 **`git pull --ff-only`**（非快进则失败退出，避免静默产生合并提交）。

自 **3.0 控制台**起，在浏览器 **「版本与更新」** 页可对 **Web 控制台静态资源** 一键下载更新；若当前进程运行在 **git 工作副本** 内，同一页可对 **Bot 主仓** 发起在线更新（写操作需控制台鉴权）。控制台在 **发布标签** 部署下会 `fetch` 后 `checkout` 到 GitHub 最新 Release 标签（要求工作区干净）；在 **非标签**（开发克隆）下会对当前分支执行 **`git pull --ff-only --autostash`**（优先使用已配置的上游分支，否则回退到 `origin` 的默认分支）。**Docker 仅镜像文件树**时该按钮会提示改用镜像更新。无论哪种方式，**更新依赖或代码后请重启 Bot 进程**。

为减少与上游冲突，自定义内容请尽量只放在 **`config/pallas.toml`**、**`data/`** 以及文档允许的挂载目录，避免直接修改 `src/` 下已纳入版本控制的文件。

## AI 功能

至此，你已经完成了牛牛基础功能的配置，包括复读、轮盘、夺舍、基本的酒后乱讲话等所有非 AI 功能
（AI 功能目前包括 唱歌、酒后闲聊、酒后 TTS 说话）

AI 功能均对设备硬件要求较高（要么有一块 6G 显存或更高的英伟达显卡，要么可能占满 CPU 且吃 10G 以上内存）
若设备性能不足，或对额外的 AI 功能不感兴趣，可以跳过这部分内容。

配置 AI 功能请移步单独的 AI 功能服务端 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)

## 作为插件部署

> [!NOTE]
> 该章节是给有 Bot 部署经验的开发者使用的，如果你只是单纯想要部署一个牛牛可以不用看这一部分
> 对于正在阅读该章节的开发者，我们假定您有一定的 [nonebot2](https://github.com/nonebot/nonebot2) 开发经验

牛牛是基于 nonebot2 来写的 Bot，那么自然支持以插件的形式部署，下面是部署指南

首先，参照上面的步骤获取牛牛的源码，安装依赖到 Bot 的运行环境，并部署好 **MongoDB 或 PostgreSQL**（使用 PG 时需 `uv sync --extra pg`）。在这之后，将 `src/common` 和 `src/plugins` 复制到现有 Bot 的目录下，其中 `src/common` 是必须复制的，而 `src/plugins` 中的插件则可以选择性启用，各插件功能如下：
+ `auto_accept`: 自动同意拉群请求
+ `block`: 黑名单功能，不回复指定用户的消息
+ `callback`：包含牛牛唱歌（tts），`sing` 和 `chat` 的回调接口
+ `chat`：牛牛酒后闲聊 **依赖于`callback`, `drink`**
+ `drink`：牛牛喝酒 **依赖于`block`**
+ `greeting`：欢迎新人/自身加群介绍
+ `repeater`：牛牛复读
+ `roulette`：牛牛开枪（轮盘）
+ `sing`：牛牛唱歌（从网易云下载）**依赖于`callback`**
+ `take_name`：牛牛夺舍，随机修改为群友 id
+ `pallas_webui`：3.0 Web 控制台（按需启用）
+ `pallas_protocol`：3.0 协议端管理（按需启用）

此外，对于多 bot 客户端，`block` 插件是必须的。

然后，你需要修改 nonebot 的 `bot.py`，添加数据库初始化的代码。关于这一步，请参照本仓库的 [`bot.py`](https://github.com/PallasBot/Pallas-Bot/blob/main/bot.py)

```diff
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

+from src.common.db import init_db
+from src.common.utils.voice_downloader import ensure_voices

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)
config = driver.config


+@driver.on_startup
+async def startup():
+    await init_db()
+    await ensure_voices()


nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
```

然后运行，你就能快乐的和牛牛聊天了~

在这种部署模式下，可能需要手动调整各插件的代码来保证牛牛的消息不会被其他插件截断。你可以统一降低牛牛各插件 `matcher` 的 `priority`（`block` 除外），同时将用户插件 `matcher` 的 `block` 统一设置为 True

## 开发者群

QQ 群: [牛牛听话！](https://jq.qq.com/?_wv=1027&k=tlLDuWzc)
欢迎加入~
