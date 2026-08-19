# 准备 Python、uv 与 PostgreSQL

> **目标**：为 Release 部署包或源码安装准备运行环境  
> **完成之后**：`uv` 可用、Python 3.12 已安装，且已准备 PostgreSQL 连接信息

本页适用于 [Release 部署包](/maintainer/install/bot) 和 [源码安装](install-source.md)。使用 [Docker 部署](/maintainer/deploy/docker) 时，Compose 会管理 Bot 与 PostgreSQL，可直接按 Docker 文档操作。

## 1. 安装 uv 与 Python 3.12

`uv` 同时管理 Python 版本和项目依赖。安装后由它准备 Python 3.12：

::: code-group

```bash [Linux / macOS]
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
```

```powershell [Windows PowerShell]
irm https://astral.sh/uv/install.ps1 | iex
uv python install 3.12
```

:::

安装脚本完成后，若终端提示找不到 `uv`，重新打开一个终端再执行 `uv --version`。

## 2. 准备 PostgreSQL

Release 与源码路径需要一个可连接的 PostgreSQL。可选择以下任一方式：

- **本机 Docker 数据库**：已安装 Docker 时，按 [源码安装：Docker 起库](install-source.md#3-准备可连接的-postgresql-数据库) 执行命令。
- **本机 PostgreSQL**：使用 [Windows 安装包](https://www.postgresql.org/download/windows/)、[macOS 安装包](https://www.postgresql.org/download/macosx/) 或 [Linux 发行版说明](https://www.postgresql.org/download/linux/) 安装后，新建空数据库 `PallasBot`。
- **托管 PostgreSQL**：使用服务商提供的主机、端口、用户、密码和数据库名。

应用账号需要能连接目标库并建表；数据库名可使用 `PallasBot`，也可使用其他名称，只需与 `pallas.toml` 保持一致。

## 3. 记录连接信息

后续填写 `config/pallas.toml` 时需要以下值：

```toml
[bootstrap.postgres]
host = "127.0.0.1"
port = 5432
user = "pallas"
password = "pallas"
db = "PallasBot"
```

本机 Docker 数据库使用上面的默认值即可。托管或已有数据库时，替换为实际连接信息。

## 下一步

- 不使用 Docker：继续 [Release 部署包安装](/maintainer/install/bot) 或 [源码安装](install-source.md)。
- 使用 Docker：直接进入 [Docker 部署](/maintainer/deploy/docker)。
