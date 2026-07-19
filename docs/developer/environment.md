# 本地开发环境

## 前置条件

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)**（依赖与虚拟环境）
- 可选：**Docker**（数据库、协议端、镜像构建校验）
- 可选：**Node.js**（仅开发 [Pallas-Bot-WebUI](https://github.com/PallasBot/Pallas-Bot-WebUI) 前端时）

## 克隆与安装依赖

```bash
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot
uv sync --dev
```

需要分片协调 Redis 时：

```bash
uv sync --dev --extra coord-redis
```

使用 PostgreSQL 时一并带上 `pg`：

```bash
uv sync --dev --extra coord-redis
```

`uv sync` 会在虚拟环境中注册 **`pallas`** 命令（见下文「统一运维 CLI」）。

## uv sync 与官方插件

`uv sync` 把 `.venv` 严格对齐 lockfile，并卸载不在本次 sync 范围内的包。下列内容不在默认 `uv sync` 里，裸跑 sync 可能被清掉：

| 类别 | 典型包 | 如何装 |
| --- | --- | --- |
| 官方插件（8 个） | `pallas-plugin-protocol`、`pallas-plugin-duel` 等 | `uv run pallas ext install <package>` 或 WebUI 插件商店 |
| 分片 Redis 客户端 | `redis` | `uv sync --extra coord-redis` 或 `uv pip install 'redis>=5.2,<6'` |
| PostgreSQL 驱动 | `sqlalchemy`、`asyncpg` | 已在主依赖；`uv sync` 即可（旧命令 `--extra pg` 仍兼容） |

约束：

- 已装官方插件或已配分片/PostgreSQL 时，勿反复执行裸 `uv sync` / `uv sync --frozen`（须带实际用到的 `--extra`）。
- 仅注册 `pallas` CLI、不动其它 pip 包：
  ```bash
  uv pip install -e . --no-deps
  ```
- 须 sync 本体依赖时，带上全部 extras，sync 后再补扩展：
  ```bash
  uv sync --extra coord-redis
  uv run pallas ext list                   # 查看应装的官方插件
  # 对 listed 里 installed=no 的逐个：
  uv run pallas ext install pallas-plugin-protocol
  # …
  ```
- **只补单个依赖、不想动扩展**时，优先 `uv pip install …`，不要用 sync。

扩展装完后需 **重启 Bot**（分片常用 `uv run pallas restart --mode shard`）。装扩展若报 hot-load 相关栈追踪，只要 `pallas ext list` 显示 `installed=yes`，重启进程即可。

## 统一运维 CLI（`pallas`）

Bot 仓库内置统一运维入口；在仓库根或任意子目录执行均可（CLI 向上查找含 `pyproject.toml` 的 Pallas-Bot 根）：

```bash
uv run pallas --help
uv run pallas doctor          # 环境检查（uv、配置、启停脚本、分片 Redis）
```

激活虚拟环境后也可直接：

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pallas status --mode shard
```

### 启停 Bot

| 场景 | 命令 |
| --- | --- |
| 单进程启动 | `uv run pallas`（等同 `uv run pallas run unified`） |
| 分片启动（hub + worker） | `uv run pallas run shard` |
| 分片：仅 hub | `uv run pallas run shard --hub-only` |
| 分片：仅补缺失 worker | `uv run pallas run shard --workers-only` |
| 查看状态 | `uv run pallas status --mode auto` |
| 停止 | `uv run pallas stop --mode auto` |
| 重启 | `uv run pallas restart --mode auto` |
| 分片：仅重启 worker | `uv run pallas restart --mode shard --workers-only` |

`--mode auto` 会根据 pid 文件与环境变量推断单进程或分片；分片部署建议显式写 `--mode shard`。

**注意**：若 worker 已全部在运行，再次 `pallas run shard` 会**跳过** worker 启动与端口重分配，避免误改 registry；需要全量重启 worker 时用 `restart --workers-only`。

### 其它常用子命令

```bash
uv run pallas sync              # 包装 uv sync
uv run pallas update bot        # git 更新本体（可加 --restart）
uv run pallas update webui      # 下载 WebUI dist
uv run pallas ext list          # 官方插件
uv run pallas plugin reload …   # 按 reload_policy 重载
uv run pallas plugin community …  # 社区插件 git 安装/更新
uv run pallas deploy shard      # 应用 deploy 分片模板
```

`./scripts/pallas` 与 `./scripts/run_*_bot.sh` 仍为兼容入口，内部由上述 CLI 调用。脚本索引见 [`scripts/README.md`](https://github.com/PallasBot/Pallas-Bot/blob/main/scripts/README.md)。

## 运行配置

**不要**再依赖根目录 `.env` 作为唯一配置源。

1. 复制主配置：

```bash
cp config/pallas.example.toml config/pallas.toml
```

2. 编辑 `config/pallas.toml`：**至少**改 `superusers` 与数据库段（见示例内「最少配置」）。新装默认 **PostgreSQL**（驱动已在主依赖）。

最少示例：

```toml
[bootstrap]
host = "0.0.0.0"
port = 8088
superusers = ["你的QQ号"]
db_backend = "postgresql"

[bootstrap.postgres]
host = "127.0.0.1"
port = 5432
user = "pallas"
password = "pallas"
db = "PallasBot"
```

从 3.x MongoDB 升级时改为 `db_backend = "mongodb"` 并填写 `[bootstrap.mongo]`（见 `config/pallas.example.toml` 注释）。

3. 其余插件与通用项在 Web 控制台保存，落盘 **`data/pallas_config/webui.json`**。

合并顺序与读取 API 见 [配置存储](/developer/architecture/config-storage)。从旧 `.env` 一次性迁移：

```bash
uv run python tools/migrate_env_to_pallas.py
```

`.env` 仍可保留 **NoneBot / pip 插件**相关项（见 `.env.example`），避免与 `webui.json` 同名键重复。

## 启动 Bot

除下述 `nb run` 与脚本外，**日常启停优先用 [统一运维 CLI](#统一运维-cli-pallas)**（`uv run pallas run unified` / `run shard`）。

单进程（最常见本地调试）：

```bash
uv run nb run
```

或使用专用启停脚本（对照测试、协议端口同步）：

```bash
./scripts/run_unified_bot.sh start
./scripts/run_unified_bot.sh status
./scripts/run_unified_bot.sh stop
```

等价 CLI：

```bash
uv run pallas run unified
uv run pallas status --mode unified
uv run pallas stop --mode unified
```

浏览器打开 `http://127.0.0.1:8088/pallas/`，使用启动日志中的口令登录。

### 分片模式（可选）

生产或多进程场景见 [多进程分片](/maintainer/deploy/sharded)。本地若需验证分片：

- 在 `pallas.toml` 的 `[env]` 配置 `REDIS_URL`（Python 端需 `redis` 包，见上文 [uv sync 与官方插件](#uv-sync-与官方插件必读)）
- 使用 `uv run pallas run shard`（会探测 Redis；worker 已运行时跳过重复启动）

```bash
uv run pallas run shard
uv run pallas status --mode shard
uv run pallas stop --mode shard
```

测试 worker（`test` / `test2` 子命令）等高级选项仍见 `./scripts/run_sharded_bot.sh -h`。

### 站点自有插件

在 `local/plugins/<name>/` 放置插件，并在 `pallas.toml` 中设置：

```toml
[bootstrap]
extra_plugin_dirs = ["local/plugins"]
```

详见 [站点定制与更新](/maintainer/deploy/upgrade)。

## 质量检查（与 CI 一致）

```bash
uv run ruff check pallas/ packages/
uv run ruff format --check pallas/ packages/
```

自动修复：

```bash
uv run ruff check --fix pallas/ packages/
uv run ruff format pallas/ packages/
```

运行测试：

```bash
uv run pytest
```

可选（与 CI 对齐，不阻断合并）：

```bash
uv run pip-audit
docker build -t test-build .
```

## pre-commit

```bash
uv run pre-commit install
uv run pre-commit run -a
```

全仓做 YAML/TOML、尾随空格等基础检查；Ruff 仅作用于 `pallas/`、`packages/`；`.env` 排除以免误改本地密钥。

## 日志习惯

loguru 风格 `logger`（NoneBot 提供）。占位符用 `{}` 或 f-string；避免 `logger.debug("msg %s", x)` 导致消息里仍显示 `%s`。

## 相关

- [贡献与提交流程](workflow.md)
- [插件开发入门](/developer/plugin-development/getting-started)
