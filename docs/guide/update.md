# 更新 Pallas-Bot

> **目标**：把已经能正常运行的 Pallas-Bot 更新到新版本  
> **完成之后**：版本更新到目标，Bot 重新运行

Docker 容器只支持正式 Release，不支持 Git 分支或 Commit 更新。

::: warning 注意：更新前备份
更新前备份 `config/pallas.toml` 和 `data/`。本地定制放在 `local/plugins/`，不要直接修改已跟踪的源码文件，否则拉取上游时可能产生冲突。
:::

## 选择更新方式

| 你的部署方式 | 推荐方式 | 适用场景 |
| --- | --- | --- |
| Docker Compose | 控制台 Release 更新或[更新 Docker 镜像](#docker-compose) | 临时更新当前容器，或持久更新镜像 |
| Release 部署包或源码目录，想由 Bot 处理 | [控制台或命令更新](#控制台或命令更新) | 想更新 Bot 或 WebUI，且当前实例可正常运行 |
| 源码目录，想自行控制过程 | [手动更新源码](#手动更新源码) | 需要先检查变更、处理定制或维护开发分支 |
| 源码 Release 部署，接受定时升级 | [Bot 自动更新](#bot-自动更新) | 希望按计划检查并应用上游更新 |

更新完成后，打开 `http://<主机>:8088/pallas/api/health`，再登录控制台确认页面不是旧版本。官方插件需要时在**插件商店**单独更新。

## Docker Compose

在保存 `docker-compose.yml` 和 `pallas-bot/` 的部署目录执行：

```bash
docker compose --env-file ./pallas-bot/config/compose.env pull
docker compose --env-file ./pallas-bot/config/compose.env up -d
docker compose --env-file ./pallas-bot/config/compose.env ps
```

这是 Docker 的持久更新方式。重建后运行版本与新镜像一致；挂载的 `config/`、`data/` 与 `local/plugins/` 会保留。完整编排与日志命令见 [Docker 部署](/maintainer/deploy/docker)。

Docker 用户也可在控制台“版本与更新”选择正式 Release。Bot 会下载官方 `pallas-bot-<tag>.tar.gz` 并覆盖当前容器内代码：`docker compose restart` 后仍保留，但 `docker compose up -d` 重建容器后会恢复为镜像版本。控制台会同时显示运行版和镜像版。需要长期保留时仍应拉取对应新镜像并重建。

## 控制台或命令更新

此方式适用于带 `.git` 的源码部署、官方部署包，以及 Docker 的 Release 覆盖更新。Docker 下不会显示 Commit、分支或 force/reset 操作。

1. 在控制台打开**版本与更新**，先检查当前版本和部署模式。
2. 选择**应用 Bot 更新**，并按需更新 WebUI。Bot 会在更新后安排重启；若页面提示无法安排重启，按你的 systemd 或启动脚本手动重启。
3. 不方便打开控制台时，在仓库根目录运行：

```bash
uv run pallas update bot --restart
uv run pallas update webui
```

也可以一次执行：

```bash
uv run pallas maintenance run --update-bot --update-webui
```

两条命令分别更新当前 Git 跟踪的 Bot 版本和 Release 中的 WebUI `dist.zip`，互不强制绑定。不要添加 `--dev`，除非此机器还需要安装测试等开发依赖。

## 手动更新源码

在 Pallas-Bot 仓库根目录执行：

```bash
git pull --ff-only
uv sync
uv run pallas update webui
```

随后按当前部署方式重启 Bot：systemd 部署使用 `systemctl restart pallas-bot`；手工启动的单进程重新运行 `uv run pallas`；分片使用 `./scripts/run_sharded_bot.sh restart`。若 `git pull` 提示本地改动，先迁走定制或自行处理冲突，不要强制覆盖。

若你固定在某个 Release tag，使用控制台的更新按钮或选择目标 tag 后再同步依赖；完整的 tag、分支和定制策略见[升级与站点定制](/maintainer/deploy/upgrade)。

## Bot 自动更新

自动更新由已运行的 Bot 按控制台设置的时间表检查更新并应用。Docker 下它更新当前容器内容，不会拉取或重建镜像。

在控制台**版本与更新**中开启 Bot 自动更新，并选择更新轨道：

| 更新轨道 | 可自动应用的部署 |
| --- | --- |
| Release | 干净的 Release tag 源码目录、官方部署包或 Docker 当前容器 |
| 分支 | 可访问 Git 的非 Docker 源码目录 |

也可由超管私聊 Bot 执行 `牛牛更新 自动 bot 开` 或 `牛牛更新 自动 bot 关`。WebUI 自动更新是独立开关，Bot 更新不会强制替换当前 WebUI。自动更新前应先确认本地定制已移到 `local/plugins/`，并启用通知，以便在更新完成后收到结果。

需要立即更新时，仍使用控制台的**应用 Bot 更新**或上面的 CLI 命令。WebUI 与插件更新是独立能力，在 Docker 下同样可用。自动更新检查和失败排查见[升级与站点定制](/maintainer/deploy/upgrade)。
