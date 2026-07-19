# AI Runtime

接入 AI Runtime。现象无响应时，按 Bot 侧 / AI 侧分层排查。

独立仓 `Pallas-Bot-AI`；Bot 通过任务与 callback 协作，不是主仓内普通插件。

::: tip
可选。不接 AI 也能跑复读与官方插件。
:::

## 两层职责

| 组件 | 职责 |
| --- | --- |
| `Pallas-Bot` | 接消息、发起任务、接收 callback、把结果送回群或会话 |
| `Pallas-Bot-AI` | 执行 AI / 媒体任务 |

任一侧异常都会表现为「AI 没反应」，根因不一定在同一仓。

### 排障分支

| 分支 | 含义 |
| --- | --- |
| Bot 未发出任务 | 总闸、权限、网关或插件未触发 |
| AI Runtime 未收到 | 地址、网络、鉴权 |
| 已执行无回调 | callback 地址或鉴权 |
| 回调到 hub 未转发 | 分片路由 / 目标 worker |

## 能力范围

- 绘图与媒体生成
- 唱歌、音频、工具类异步任务
- 任务状态回调与结果回传
- **@ 对话、接话 LLM、醉聊**（4.0 智能对话）

::: tip
普通复读、帮助、权限、扩展玩法：本体 + 扩展即可。仅在需要 @ 闲聊、接话 LLM、画图 / 唱歌等时再接 AI Runtime。
:::

## 安装（维护者）

### 本机开发（推荐）

在 **Pallas-Bot-AI** 仓库：

```bash
cp .env.example .env
./scripts/ai_bootstrap.sh --bot-host 127.0.0.1 --bot-port 8088
```

默认只装 **LLM 栈**（不装 torch），启动 llm worker + API，够用 @ 闲聊 / 接话。

或在 **Pallas-Bot** 仓库（同级已克隆 AI 仓时）：

```bash
uv run pallas ai setup
```

也可在控制台 **AI 配置 · 连接** 使用「安装 AI Runtime（源码）」：克隆同级 `Pallas-Bot-AI` 并跑 `ai_bootstrap.sh`；成功且连接配置为空时会写入默认 `http://127.0.0.1:9099`。Docker 请在宿主机自行执行（控制台不代跑）。

| 场景 | 命令 |
| --- | --- |
| 仅体检 | `uv run pallas ai setup --check-only` |
| Bot 非默认端口 | `--bot-port <port>` |
| 远端 API、不用 Ollama | `--remote-only` |
| 唱歌 / TTS / 醉聊 RWKV | `--with-media`（装 torch CPU） |
| 媒体 + NVIDIA torch | `--with-media --gpu` |

本地 Ollama 推理用 Ollama 自带 GPU，与 `--gpu`（本仓 PyTorch）无关。

### 无 GPU / 纯第三方 API（remote-only）

服务器跑不动 Ollama 时，仍可用 DeepSeek、OpenAI 等 OpenAI 兼容 API 驱动 @ 闲聊与接话 LLM。需轻量 AI 仓（Redis + API + Celery），**不需要**本地模型，也**不需要** torch。

```bash
# AI 仓：编辑 .env 填入 LLM_REMOTE_* 后
./scripts/ai_bootstrap.sh --remote-only --bot-port 8088

# 或 Bot 仓
uv run pallas ai setup --remote-only --bot-port 8088
```

完整配置、Docker 仅起 `redis`+`pallasbot-ai`、验收与排障见 **[Pallas-Bot-AI · remote-only 部署](https://github.com/PallasBot/Pallas-Bot-AI/blob/main/docs/deploy/remote-only.md)**。

### Docker（仅 AI 栈）

```bash
docker compose -f docker-compose.llm.yml up -d
```

### 与 Bot 同编排（新装）

使用主仓 **`docker-compose.full.yml`**（PostgreSQL + Bot + Redis + Ollama + AI），见 [Docker 部署](/deploy/docker)。

### Bot 侧最小配置

`config/pallas.toml` 的 `[env]` 或 WebUI「智能对话与 AI 服务」：

- `LLM_CHAT_ENABLED=true`
- `AI_SERVER_HOST` / `AI_SERVER_PORT`（默认 `127.0.0.1:9099`；全栈 compose 内由环境注入）

详细变量见 [Pallas-Bot-AI README](https://github.com/PallasBot/Pallas-Bot-AI/blob/main/README.md) 与 [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)。

从 0 安装验收见 [安装验收 Checklist](ga-install-checklist.md)。

## 接入前核对

### 1. 地址与可达性

- AI Runtime 基址
- Bot 发任务的目标地址
- AI Runtime 回调 Bot 的 callback 地址

::: warning
分片下 callback 须回到 hub，不要指向任意 worker。
:::

### 2. token 与鉴权

两边不一致时常见：

- 任务提交看似成功、实际被拒绝
- callback 到达但 Bot 拒收

### 3. 网络路径

Docker、多机或反代场景核对：

- AI Runtime 能否访问 hub 的 callback
- 是否把内网地址写给了外部服务
- 端口与反代转发是否完整

### 4. Bot 侧能力已启用

- 对应插件或能力已安装
- 服务网关配置正确
- WebUI 运行态与真实配置一致

## 联调顺序

1. 跑通 Bot 本体
2. 启动 AI Runtime
3. 在 Bot 侧填写地址、token、网关
4. 确认 AI Runtime 能访问 Bot 的 callback
5. 触发最小任务验证整条链路
6. 核对照 WebUI 中的 AI 状态与任务结果

## 分片要点

- callback 回到 hub
- worker 登记的任务由 hub 转发到对应 worker
- AI Runtime 能访问 worker、访问不到 hub，不能替代正确 callback 配置

::: tip
分片下 AI 无回执：优先查回调路径。
:::

## 按现象检查

### 任务发出但没有结果

- AI Runtime 是否收到任务
- 任务是否执行失败
- callback 是否打回 Bot

### 页面显示 AI 离线

- 运行态探测接口
- 服务地址是否填错
- WebUI 状态是否过期，或后端探测失败

### 群里没有任何回执

- Bot 是否发起了任务
- callback 是否回到 hub
- hub 是否转发到登记任务的 worker

## 相关阅读

- [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)
- [架构总览](/developer/architecture/overview)
