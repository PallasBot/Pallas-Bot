# AI Runtime

本页说明如何接入 AI Runtime，它提供唱歌 / TTS 等媒体能力与遗留 RWKV 对话。普通 LLM 聊天在 Bot WebUI「AI 配置 → 接入」配置 Provider。

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

日常运维在 AI Runtime 根目录执行：

```bash
uv run pallas-ai start          # 同时启动 API 与 media worker
uv run pallas-ai status
uv run pallas-ai restart media  # 仅重启媒体任务进程
uv run pallas-ai purge-stale    # 仅在需要清理遗留 Celery 任务状态时执行
```

`pallas-ai` 是单一命令入口，但 API 与 media worker 仍为独立进程；媒体进程异常或重启不会主动停止 API。

**Windows**：媒体栈依赖 Redis。bootstrap 默认 `docker compose` 拉起，先安装并启动 [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)（托盘就绪）；或本机/WSL 自备 Redis 并设置 AI 仓 `.env` 的 `REDIS_URL`。失败时以脚本日志提示为准。

唱歌 / TTS 还需要本机 **ffmpeg** 在 PATH 中（否则日志会出现 `Couldn't find ffmpeg`，音频处理可能失败）。可用：

```powershell
winget install --id Gyan.FFmpeg -e
```

装完后**新开终端**，再在控制台重启媒体服务。也可把 `ffmpeg.exe` / `ffprobe.exe` 放到 AI Runtime 目录后确保 PATH 能找到。

从 Bot 控制台启动 AI 时，若曾看到 `VIRTUAL_ENV=…\Pallas-Bot\.venv does not match`：那是 Bot 虚拟环境变量泄漏到 AI 仓，**可忽略**；新版启停会自动剥掉该变量。`pydub` 的 `SyntaxWarning: invalid escape sequence` 来自第三方库，也不影响使用。

或在 **Pallas-Bot** 仓库（同级已克隆 AI 仓时）：

```bash
uv run pallas ai setup
```

也可在控制台 **AI 配置 · 媒体服务** 使用安装：未安装时「下载并安装」；托管目录（`data/runtimes/pallas-bot-ai`）打开/刷新会 `git fetch` 对比远端，有更新才显示「更新 Runtime」（`git pull --ff-only` 后再 bootstrap），已是最新则只留「仅重装依赖」；成功且连接配置为空时会写入默认 `http://127.0.0.1:9099`。Docker 宿主机上自行执行（控制台不代跑）。

用户向手把手与 **能力包**（对话模型拉取、媒体权重 / Docker 换 `latest`）见 [AI 扩展](/guide/ai)。

| 场景 | 命令 |
| --- | --- |
| 仅体检 | `uv run pallas ai setup --check-only` |
| Bot 非默认端口 | `--bot-port <port>` |
| 媒体 + NVIDIA torch | `uv run pallas ai setup --gpu` |

`--gpu` 安装 AI Runtime 的 **torch 2.7.1 + cu128**（支持 RTX 50 / `sm_120`）；驱动需支持 CUDA 12.8。从旧 cu124 环境升级后「仅重装依赖」或再跑一次带 `--gpu` 的 setup。

本地 Ollama 推理（若仍用遗留 LLM worker）用 Ollama 自带 GPU，与 `--gpu`（本仓 PyTorch）无关。

### 无 GPU / 纯第三方 API

普通聊天在 Bot WebUI「AI 配置 → 接入」配置 Provider、模型和密钥即可，不需要运行本 Runtime。

### Docker（仅 AI 栈）

```bash
docker compose -f docker-compose.llm.yml up -d
```

### 与 Bot 同编排（新装）

使用文档站 [Docker 部署 · 全栈](/maintainer/deploy/docker) 中的示例 YAML（PostgreSQL + Bot + Redis + Ollama + AI），本地另存后启动。

AI 镜像仅用于媒体 / RWKV。Ollama 模型默认不预拉（`--profile pull-models` 可选）。在 WebUI「AI 配置 → 媒体服务」保存连接时，会同步 Bot 侧 `AI_SERVER_HOST` / `AI_SERVER_PORT`，以及 Bearer → `TTS_API_TOKEN`（供 TTS `/v1` 鉴权）；策略页与唱歌/TTS 插件页不再单独填服务地址。

### Bot 侧最小配置

`config/pallas.toml` 的 `[env]` 或 WebUI：

- 普通聊天：在 **AI 配置 → 接入** 配置 Provider，并打开 `LLM_CHAT_ENABLED`
- 媒体或遗留 RWKV：再配 `AI_SERVER_HOST` / `AI_SERVER_PORT`（默认 `127.0.0.1:9099`；也可由扩展基址同步）

详细变量见 [Pallas-Bot-AI README](https://github.com/PallasBot/Pallas-Bot-AI/blob/main/README.md) 与 [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)。

从 0 安装验收见 [安装验收 Checklist](ga-install-checklist.md)。

### 手动补充 DDSP-SVC 多版本（可选）

默认安装只会检出 **一份** 唱歌推理代码：`app/workers/sing/DDSP-SVC`（对应 **6.2**）。`ai_bootstrap.sh` 会初始化它；若源码仓已存在但该目录为空，可在 AI Runtime 根目录恢复默认子模块：

```bash
git submodule update --init app/workers/sing/DDSP-SVC
```

控制台「优先后端」若选 `ddsp_6.3` / `ddsp_6.1`，需要本地另有对应目录；新版本 Runtime 可在缺脚本时后台自动拉取，直连 GitHub 失败时也可按下述**手动**安装。

| 版本 | 优先后端 ID | 本地目录 | Git 分支 |
| --- | --- | --- | --- |
| 6.2（默认） | `ddsp_6.2` | `app/workers/sing/DDSP-SVC` | `6.2` |
| 6.3 | `ddsp_6.3` | `app/workers/sing/DDSP-SVC-6.3` | `6.3` |
| 6.1 | `ddsp_6.1` | `app/workers/sing/DDSP-SVC-6.1` | `6.1` |

在 **AI Runtime 根目录**执行（同级源码仓，或托管目录如 `data/runtimes/pallas-bot-ai`）。`git clone` 的仓库地址与目标目录须写在**同一条命令**里。

**PowerShell（本机代理；把 `7890` 改成你的端口）——可多行整段粘贴：**

```powershell
cd F:\Pallas-Bot\Pallas-Bot\data\runtimes\pallas-bot-ai
$env:HTTPS_PROXY="http://127.0.0.1:7890"
$env:HTTP_PROXY="http://127.0.0.1:7890"
Remove-Item -Recurse -Force app\workers\sing\DDSP-SVC-6.3 -ErrorAction SilentlyContinue
git clone --depth 1 --branch 6.3 https://github.com/PallasBot/DDSP-SVC.git app/workers/sing/DDSP-SVC-6.3
```

**终端吃不到系统代理时，用镜像（不必设 PROXY）：**

```powershell
cd F:\Pallas-Bot\Pallas-Bot\data\runtimes\pallas-bot-ai
Remove-Item -Recurse -Force app\workers\sing\DDSP-SVC-6.3 -ErrorAction SilentlyContinue
git clone --depth 1 --branch 6.3 https://ghproxy.net/https://github.com/PallasBot/DDSP-SVC.git app/workers/sing/DDSP-SVC-6.3
```

镜像不可用时可换：`gh-proxy.com`、`ghproxy.vip`、`ghproxy.net`（写法同为 `https://<镜像>/https://github.com/PallasBot/DDSP-SVC.git`）。装 **6.1** 时把分支改成 `--branch 6.1`、目录改成 `app/workers/sing/DDSP-SVC-6.1`。

Linux / macOS 示例：

```bash
cd /path/to/pallas-bot-ai   # 或 data/runtimes/pallas-bot-ai
export HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890
rm -rf app/workers/sing/DDSP-SVC-6.3
git clone --depth 1 --branch 6.3 https://github.com/PallasBot/DDSP-SVC.git app/workers/sing/DDSP-SVC-6.3
```

::: tip
每份约 1.6G。6.2+ 与旧 checkpoint **不兼容**——权重按哪个版本训的，就优先用哪个后端；不要指望同一份 `.pt` 跨 6.1/6.2/6.3 通吃。装完后在控制台重启媒体服务。

控制台「AI 配置 → 媒体」可为**每个音色**单独指定优先推理（`speaker_backends`）。官方 `pallas`（`config.yaml` 里 `RectifiedFlow`）对应 **6.2**，建议选 `ddsp_6.2`；**6.1** 只给旧扩散权重用，不是现网官方音色。
:::

#### DDSP 权重与音色

优先在控制台 **AI 配置 → 媒体 → 媒体资产** 下载官方 `sing_pallas` 和 `sing_pretrain`：前者提供官方 `pallas` 音色，后者提供 DDSP 预训练资产。自备 DDSP 音色必须将 `*.pt` 与同目录 `config.yaml` 一起放入 `resource/sing/models/<音色 id>/`；缺少 `config.yaml` 时推理会失败。

| 后端 | 音色 | 必需共享权重 |
| --- | --- | --- |
| `ddsp_6.2` / `ddsp_6.1` | `resource/sing/models/<id>/<name>.pt` + `config.yaml` | `resource/sing/models/pretrain/contentvec/checkpoint_best_legacy_500.pt`、`resource/sing/models/pretrain/rmvpe/model.pt`，以及音色 `config.yaml` 指向的 NSF / PC-NSF HiFiGAN 目录 |
| `ddsp_6.3` | 同上；权重需由 6.3 训练 | `resource/sing/models/pretrain/contentvec/pytorch_model.bin`；首次使用会从 [lengyue233/content-vec-best](https://huggingface.co/lengyue233/content-vec-best) 自动下载 |

不要跨版本混用 DDSP `.pt`。`sing_pretrain` 是默认来源；若手工准备，以该音色的 `config.yaml` 中 `encoder_ckpt` 与 vocoder 路径为准。

社区训练的 DDSP-SVC / RVC 音色可在 [TogetsuDo on Hugging Face](https://huggingface.co/TogetsuDo) 获取；下载后仍须按本节要求准备匹配的配置与共享权重。

### 社区 RVC 音色（可选第三后端）

唱歌 registry 在 DDSP / SoVITS 之外支持 **`rvc`**：社区常见 `.pth`（+ 可选 `.index`）可直接当 Speaker。回退顺序默认 `DDSP → RVC → SoVITS`；仅有 `.pth` 的目录不会误进 DDSP（DDSP 认 `*.pt`）。

| 项 | 路径 / 说明 |
| --- | --- |
| 引擎子模块 | `app/workers/sing/RVC`（[RVC WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)） |
| 薄入口 | `app/workers/sing/rvc_launcher/infer_rvc.py` |
| 音色目录 | `resource/sing/models/<id>/*.pth`，可选同 stem 或唯一一个 `*.index` |
| 共享资产 | `resource/sing/models/pretrain/rvc/hubert_base/`、`rmvpe.pt`（[lj1995/VoiceConversionWebUI](https://huggingface.co/lj1995/VoiceConversionWebUI)） |

在 AI Runtime 根目录初始化引擎、安装依赖并下载共享权重：

```bash
cd /path/to/pallas-bot-ai
git submodule update --init app/workers/sing/RVC
uv sync --group sing   # 含 av、faiss-cpu、ffmpeg-python
python -m pip install --upgrade huggingface_hub
hf download lj1995/VoiceConversionWebUI --revision main \
  --include "hubert_base/*" --local-dir resource/sing/models/pretrain/rvc
hf download lj1995/VoiceConversionWebUI rmvpe.pt --revision main \
  --local-dir resource/sing/models/pretrain/rvc
```

下载完成后应是：

```text
resource/sing/models/pretrain/rvc/
├── hubert_base/
│   ├── config.json
│   ├── preprocessor_config.json
│   └── pytorch_model.bin
└── rmvpe.pt
```

若已有旧版 fairseq `hubert_base.pt`，可放在 `resource/sing/models/pretrain/rvc/hubert_base.pt`（或 `hubert_base/hubert_base.pt`），再执行：

```bash
uv run python tools/convert_rvc_hubert.py
```

它会生成上述 Transformers `hubert_base/` 目录。Windows 无软链接权限时，也可直接将同一批文件放到 `app/workers/sing/RVC/assets/hubert_base/` 与 `app/workers/sing/RVC/assets/rmvpe/rmvpe.pt`。

控制台优先后端可选 `rvc`。v1/v2 从 checkpoint 元数据识别，无需手填。RVC 音色必须使用可推理的 `*.pth`，不要放训练过程的 `G_*.pth`；`.index` 可选。细节见 AI 仓 [Deployment.md](https://github.com/PallasBot/Pallas-Bot-AI/blob/main/docs/Deployment.md)。

## 接入前核对（媒体）

默认 LLM 聊天只核对 Provider。下列项针对 **媒体任务**。

### 1. 地址与可达性

- AI Runtime 基址
- Bot 发任务的目标地址
- AI Runtime 回调 Bot 的 callback 地址

::: warning 注意：分片 callback
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
