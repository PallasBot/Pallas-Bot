# 4.0 安装验收 Checklist

维护者从 **0** 安装时按本清单走查。每条打勾前记录 **日期 / 环境**（OS、GPU、Docker 版本）；失败项记录现象与日志路径。

**相关文档**：[Docker 部署](/deploy/docker) · [AI Runtime](ai-runtime.md) · [运维入口](/maintainer/quickstart) · [升级](/maintainer/deploy/upgrade)

---

## 0. 走查前准备

| 项 | 要求 |
| --- | --- |
| 机器 | 干净目录；建议 ≥ 8GB 内存；全栈 + Ollama 建议 ≥ 16GB 或接受 CPU 推理较慢 |
| Docker | `docker --version`、`docker compose version` 有输出（Docker 路径） |
| 网络 | 可拉取 `pallasbot/*` 镜像与 Ollama 模型（首次约 15–40 分钟） |
| 端口 | 宿主机 **8088**（Bot）、**9099**（AI，全栈时）未被占用 |
| 仓库 | 仅 compose 时可不克隆；本机开发须克隆 **Pallas-Bot**；AI 本机路径须同级 **Pallas-Bot-AI** |

---

## 路径 A：Docker 全栈新装

**目标**：Bot + PostgreSQL + Redis + Ollama + AI，单条 compose 启动。

### A1. 准备目录与配置

- [ ] 新建部署目录（例 `~/pallas-deploy`）；Compose 项目目录名勿含中文或空格
- [ ] 复制 `docker-compose.full.yml`、（可选）`docker-compose.full.gpu.yml`
- [ ] `mkdir -p pallas-bot/config pallas-bot/data pallas-bot-ai/logs`
- [ ] 复制 `config/pallas.example.toml` → `pallas-bot/config/pallas.toml`
- [ ] 编辑 `pallas.toml`：`superusers`；`db_backend = "postgresql"` 与 `[bootstrap.postgres]` 一致
- [ ] 复制 `config/compose.env.example` → `pallas-bot/config/compose.env`；**`PG_*` 与 TOML postgres 段一致**

### A2. 启动

```bash
cd ~/pallas-deploy
docker compose -f docker-compose.full.yml --env-file ./pallas-bot/config/compose.env up -d
# NVIDIA GPU: 追加 -f docker-compose.full.gpu.yml
# 可选预拉 Ollama 模型: 追加 --profile pull-models（默认不预拉，改在 WebUI 拉）
```

- [ ] `docker compose ... ps`：`pallasbot`、`postgres`、`redis`、`pallasbot-ai`、`ollama` 为 **running/healthy**（默认无 `ollama-init`；仅加了 `--profile pull-models` 时可为 **exited 0**）
- [ ] AI 默认镜像为 **`pallasbot/pallas-bot-ai:slim`**（LLM-only）；唱歌/TTS 等需在 `compose.env` 设 `PALLAS_AI_IMAGE=pallasbot/pallas-bot-ai:latest` 并叠加 GPU compose
- [ ] 未用 `pull-models` 时：进 WebUI「AI 配置 → 接入 / 模型」配置 provider 并拉取模型（可勾选「切换时拉取」）

**失败分支**：某服务非 healthy → `docker compose logs <服务名>`；PG 见 [Docker 部署 · PG 排障](/deploy/docker)。

### A3. 探活

```bash
curl -s http://127.0.0.1:8088/pallas/api/health | python3 -m json.tool
curl -s http://127.0.0.1:9099/health | python3 -m json.tool
```

- [ ] Bot health 返回 JSON（非连接拒绝）
- [ ] AI health：`llm.configuration_ok` 为 true 或 `provider_status` 本地可达
- [ ] 浏览器 `http://<宿主机>:8088/pallas/` 可进登录 / Setup Wizard

### A4. 控制台与配置

- [ ] 首次登录完成 Setup Wizard（改密、协议端可稍后）
- [ ] WebUI「智能对话与 AI 服务」显示 AI 在线或探测成功
- [ ] `data/pallas_config/webui.json` 已生成（卷持久化）

### A5. 协议端与群（可选）

- [ ] `http://<宿主机>:8088/pallas/protocol` 可创建 / 管理协议端实例
- [ ] QQ 连上后群内 **牛牛帮助** 有响应
- [ ] 开启 LLM 后 `@牛牛` 或智能对话有一条成功回复（首次可能较慢）

### A6. 收尾

- [ ] `docker compose ... down` 后 `up -d` 再探活；`pallas-bot/data`、`postgres/data` 数据仍在
- [ ] 记录总耗时与卡点（模型下载、health 超时等）

---

## 路径 B：本机开发（uv）

**目标**：本机 Bot + 可选 AI bootstrap。

### B1. Bot 本体

```bash
cd /path/to/Pallas-Bot
uv sync --dev
cp config/pallas.example.toml config/pallas.toml
# 编辑 superusers；本地 PG 或 mongodb 段
uv run pallas doctor
uv run pallas
```

- [ ] `pallas doctor` 无致命项
- [ ] `http://127.0.0.1:8088/pallas/api/health` 正常
- [ ] WebUI 可登录

### B2. AI Runtime（同级仓）

```bash
cd /path/to/Pallas-Bot
uv run pallas ai path               # 应输出 ../Pallas-Bot-AI
uv run pallas ai setup
# 唱歌/TTS: uv run pallas ai setup --with-media
```

- [ ] Redis 可达（脚本可自动 `docker compose -f docker-compose.4.0-ci.yml up -d`）
- [ ] Ollama 或远端 LLM 配置正确（`--remote-only` 跳过 Ollama）
- [ ] `curl -s http://127.0.0.1:9099/health` 正常
- [ ] Bot `pallas.toml` 或 WebUI：`LLM_CHAT_ENABLED=true`，`AI_SERVER_HOST`/`PORT` 指向 AI
- [ ] （可选）`--with-media` 后 media worker 就绪

### B3. LLM 联调（可选）

```bash
cd /path/to/Pallas-Bot
uv run python tools/integration_llm_chat.py --ai-port 9099
```

- [ ] 脚本无致命错误（按脚本提示配置 PG/Mongo 与测试环境变量）

---

## 路径 C：仅 AI Docker（Bot 在宿主机或其他机器）

```bash
cd /path/to/Pallas-Bot-AI
docker compose -f docker-compose.llm.yml up -d
# GPU: 追加 -f docker-compose.llm.gpu.yml
```

- [ ] `9099/health` 正常
- [ ] Bot 侧 `CALLBACK_HOST`：同机 Docker 用 `host.docker.internal`；Bot 在 compose 内用服务名 `pallasbot`
- [ ] Bot 发起 AI 任务可收到 callback（WebUI 运行态或群内 LLM 回复）

---

## 路径 D：3.x 升级 / 沿用 MongoDB

**目标**：老数据卷不动，验证升级后仍可运行。

- [ ] 升级前备份：`pallas-bot/data/`、`mongo/data/`、`pallas.toml`
- [ ] `pallas.toml` 保持 `db_backend = "mongodb"` + `[bootstrap.mongo]`
- [ ] 使用根目录 **`docker-compose.yml`**（非 `full`）；勿换 PG 卷
- [ ] `docker compose up -d` 后 Bot health 正常
- [ ] 历史群数据、语料、配置仍在（抽一条已知数据核对）
- [ ] （可选）`uv run python tools/migrate_env_to_pallas.py` 仅从旧 `.env` 迁移一次

**注意**：改 `db_backend` **不会**自动迁数据。新装默认 PG；迁 PG 须单独迁移方案，不在本清单范围。

---

## 路径 E：仅 Bot + Mongo/PG（不含 AI）

适用：先跑通本体与 WebUI，暂不接智能对话。

| 栈 | 命令 |
| --- | --- |
| Mongo（升级栈） | `docker compose up -d` |
| PG（分步） | `docker compose --env-file ./pallas-bot/config/compose.env --profile postgres up -d` |

- [ ] health + WebUI + 帮助菜单
- [ ] 不接 AI 时群内无 LLM 属预期

---

## 常见问题速查

| 现象 | 先查 |
| --- | --- |
| compose 项目名为空 | 部署目录名含特殊字符；compose 已设 `name:` |
| `pallas.toml` not a directory | 挂载路径误建成文件夹 |
| PG `pg_isready` 失败 | `compose.env` 的 `PG_*` 与 TOML 不一致；或旧 `postgres/data` 库名冲突 |
| AI health 失败 | `docker compose logs pallasbot-ai`；Redis/Ollama 是否 healthy |
| 群无 LLM 回复 | callback 地址；`LLM_CHAT_ENABLED`；AI 日志与 Bot 同网段 |
| 帮助图样式异常 | 勿将整个 `resource` 挂到 `/app/resource`（见 [Docker 部署](/deploy/docker)） |

更多：[FAQ](/deploy/faq) · [排障](/maintainer/operate/troubleshooting) · [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)

---

## GA 发布前维护者附加项

- [ ] 三仓 `dev-v2` CI 全绿
- [ ] 本清单路径 **A + B** 至少在一种环境完整走通并记录
- [ ] CHANGELOG / 4.0 迁移指南与 compose 默认一致
- [x] `pallas-core` wheel 构建与 PyPI 发布（`.github/workflows/publish-pypi-core.yml`，随 `v*` tag）
- [ ] 镜像 tag 与 compose 中 `latest` 是否改为固定版本（发布策略）

---

## 记录模板

```text
日期：
环境：OS / RAM / GPU / Docker 版本
路径：（A/B/C/D/E）
结果：通过 / 部分通过
失败项：
日志：
备注：
```
