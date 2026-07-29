# AI Runtime

本页说明如何接入可选的 AI Runtime（媒体 / 遗留 RWKV）。普通 LLM 聊天请在 Bot WebUI「AI 配置 → 接入」配置 Provider，不依赖本 Runtime。

独立仓是 `Pallas-Bot-AI`；Bot 通过任务与 callback 协作，不是主仓内普通插件。

::: tip
可选。不接 AI Runtime 也能跑复读、官方插件与普通 LLM 对话。
:::

## 两层职责

| 组件 | 职责 |
| --- | --- |
| `Pallas-Bot` | 接消息、配置 Provider 并在进程内完成普通 LLM 聊天；媒体 / RWKV 时发起任务、接收 callback |
| `Pallas-Bot-AI` | 执行媒体任务与遗留 RWKV `/api/chat` |

任一侧异常都会表现为「AI 没反应」，根因不一定在同一仓。

### 排障分支

| 分支 | 含义 |
| --- | --- |
| Bot 未发出任务 | 总闸、权限、网关或插件未触发 |
| AI Runtime 未收到 | 地址、网络、鉴权 |
| 已执行无回调 | callback 地址或鉴权 |
| 回调到 hub 未转发 | 分片路由 / 目标 worker |

## 能力范围

- 唱歌、TTS 等媒体异步任务
- 可选遗留酒后 RWKV
- 任务状态回调与结果回传

::: tip
普通复读、帮助、权限、扩展玩法：本体 + 扩展即可。默认 LLM 聊天只配 **接入** Provider；唱歌 / TTS 等媒体再接 AI Runtime。
:::

## 安装（维护者）

### 本机开发（推荐）

在 **Pallas-Bot-AI** 仓库：

```bash
cp .env.example .env
./scripts/ai_bootstrap.sh --bot-host 127.0.0.1 --bot-port 8088
```

默认安装 **媒体栈**（含 torch），启动 media worker + API。普通聊天不经本 Runtime。

或在 **Pallas-Bot** 仓库（同级已克隆 AI 仓时）：

```bash
uv run pallas ai setup
```

也可在控制台 **AI 配置 · 媒体服务** 使用安装：克隆同级 `Pallas-Bot-AI` 并跑 `ai_bootstrap.sh`；成功且连接配置为空时会写入默认 `http://127.0.0.1:9099`。Docker 请在宿主机自行执行（控制台不代跑）。

用户向手把手与 **能力包**（对话模型拉取、媒体权重 / Docker 换 `latest`）见 [AI 扩展](/guide/ai)。

| 场景 | 命令 |
| --- | --- |
| 仅体检 | `uv run pallas ai setup --check-only` |
| Bot 非默认端口 | `--bot-port <port>` |
| 媒体 + NVIDIA torch | `uv run pallas ai setup --gpu` |

本地 Ollama 推理（若仍用遗留 LLM worker）用 Ollama 自带 GPU，与 `--gpu`（本仓 PyTorch）无关。

### 无 GPU / 纯第三方 API

普通聊天在 Bot WebUI「AI 配置 → 接入」配置 Provider、模型和密钥即可，不需要运行本 Runtime。

### Docker（仅 AI 栈）

```bash
docker compose -f docker-compose.llm.yml up -d
```

### 与 Bot 同编排（新装）

使用文档站 [Docker 部署 · 全栈](/deploy/docker) 中的示例 YAML（PostgreSQL + Bot + Redis + Ollama + AI），本地另存后启动。

AI 镜像仅用于媒体 / RWKV。Ollama 模型默认不预拉（`--profile pull-models` 可选）。在 WebUI「AI 配置 → 媒体服务」保存连接时，会同步 Bot 侧 `AI_SERVER_HOST` / `AI_SERVER_PORT`，以及 Bearer → `TTS_API_TOKEN`（供 TTS `/v1` 鉴权）；策略页与唱歌/TTS 插件页不再单独填服务地址。

### Bot 侧最小配置

`config/pallas.toml` 的 `[env]` 或 WebUI：

- 普通聊天：在 **AI 配置 → 接入** 配置 Provider，并打开 `LLM_CHAT_ENABLED`
- 媒体或遗留 RWKV：再配 `AI_SERVER_HOST` / `AI_SERVER_PORT`（默认 `127.0.0.1:9099`；也可由扩展基址同步）

详细变量见 [Pallas-Bot-AI README](https://github.com/PallasBot/Pallas-Bot-AI/blob/main/README.md) 与 [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)。

从 0 安装验收见 [安装验收 Checklist](ga-install-checklist.md)。

## 接入前核对（媒体）

默认 LLM 聊天只核对 Provider。下列项针对 **媒体任务**。

### 1. 地址与可达性

- AI Runtime 基址
- Bot 发任务的目标地址
- AI Runtime 回调 Bot 的 callback 地址

::: warning
分片下 callback 须回到 hub，不要指向任意 worker。
:::

### 2. token 与鉴权

媒体连接里的 **Bearer Token** 须与 AI 侧 `PALLAS_AI_API_TOKEN` 一致（保存后写入 `TTS_API_TOKEN`）。两边不一致时常见：

- `/v1` 任务提交 401
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
- [运维入口](/maintainer/quickstart)
