# Release 部署包安装

> **目标**：通过 Release 部署包安装 Pallas-Bot 并完成首次启动  
> **完成之后**：Bot 可运行、网页控制台可访问；接入协议端后即可连 QQ

Release 部署包适合不使用 Docker、也不准备修改 Bot 本体的长期部署。Docker 与源码路径见文末。

## 开始前准备

1. 按 [环境准备](/guide/prepare-environment) 安装 `uv`、Python 3.12，并准备 PostgreSQL 连接信息。3.x 升级可沿用 MongoDB，见 [配置参考](/maintainer/reference/config)。
2. 从 [GitHub Releases](https://github.com/PallasBot/Pallas-Bot/releases/latest) 下载当前版本的 `pallas-bot-<version>.tar.gz`。

## 1. 解压部署包

::: code-group

```bash [Linux / macOS]
tar -xzf pallas-bot-<version>.tar.gz
cd pallas-bot-<version>
```

```powershell [Windows PowerShell]
tar -xzf pallas-bot-<version>.tar.gz
Set-Location pallas-bot-<version>
```

:::

::: details Windows：没有 `tar`
使用 7-Zip 或其他解压工具依次解开 `.gz` 与 `.tar`，进入得到的 `pallas-bot-<version>` 目录后继续下一步。
:::

## 2. 安装依赖并生成配置

```bash
uv sync --extra perf
```

::: code-group

```bash [Linux / macOS]
cp config/pallas.example.toml config/pallas.toml
```

```powershell [Windows PowerShell]
Copy-Item config\pallas.example.toml config\pallas.toml
```

:::

编辑 `config/pallas.toml`，填写 `[bootstrap] superusers` 与 `[bootstrap.postgres]`。数据库连接示例和建库方式见 [源码安装：准备数据库](/guide/install-source#3-准备可连接的-postgresql-数据库)。

## 3. 启动并验证

```bash
uv run pallas
```

启动日志出现网页控制台初始密码，且浏览器能打开 `http://<主机>:8088/pallas/` 时，本体已启动。后续步骤见 [连接 QQ](/guide/connect-qq)。

部署包包含对应版本的 WebUI 与 Release 更新所需的浅层 Git 元数据。`config/pallas.toml`、`data/` 和 `local/plugins/` 保留在部署目录中，更新策略见 [更新 Pallas-Bot](/guide/update)。

## 安装后继续配置

1. 打开 [网页控制台](/guide/web-console)，登录并查看运行状态。
2. 按 [连接 QQ](/guide/connect-qq) 接入协议端与机器人账号。
3. 为每只牛牛配置 [号主](/guide/bot-owner)，再安装需要的 [插件](/guide/install-plugins)。
4. 上线前走查 [安装验收 Checklist](ga-install-checklist.md)。

## 其他安装路径

- 希望由 Compose 同时管理 Bot、PostgreSQL 和控制台时，使用 [Docker 部署](/maintainer/deploy/docker)。宿主机不需要安装 Python、`uv` 或 PostgreSQL。
- 需要修改本体、运行测试或提交 PR 时，使用 [源码安装](/guide/install-source)。
