# 接话行为 · LLM 接入路线图

> **目标版本：4.0**（见 [pallas-4.0-roadmap](pallas-4.0-roadmap.md)）。语言层 LLM **运行时依赖 [Pallas-Bot-AI](pallas-ai-service.md)**；主仓 `features/llm` 负责 persona、工具与业务路由，AI 仓 4.0 并行重构统一网关。

## 三层分工

| 层 | 模块 | 输入 | 输出 | 是否依赖 LLM |
| --- | --- | --- | --- | --- |
| 统计层 | `group_profiler` / `style_profile` | 本机 `message`、`Context.answers` | 群风格 JSON | 否 |
| 行为层 | `resolve_persona` / `scorer` | `bot_id` + 可选 `group_id` | 阈值、选句权重 | 否 |
| 语言层 | `compile_persona_prompt` + LLM 运行时 | persona + 会话上下文 | 生成/改写文本 | 是 |

原则：**统计与行为在本地完成**；LLM 只负责「说什么、怎么说」，且默认关闭。

```
derive_persona_from_bot_id(bot_id)
      × group style_profile.derived     # 行为倍率，见 group-style-persona.md
      → resolve_persona                 # repeater 阈值 / 选句

compile_group_style_snapshot/profile  # 群风格契约（已实现）
      ↓
compile_persona_prompt(bot, group)  # 已实现
      ↓
features/llm → /api/v1/chat/completions  # 已实现（统一 Chat API）
      ↓
repeater fallback / polish            # 骨架已实现，默认关（LLM_FALLBACK/POLISH_ENABLED）
```

## 与共享语料的关系

| 能力 | 读路径 | 参与群风格？ | 参与 LLM prompt？ |
| --- | --- | --- | --- |
| 本机语料 | `make_local_context_repository()` | **是**（唯一来源） | 可选（会话 / 检索片段） |
| 共享语料 | `make_context_repository()`（Composite） | **否** | 可选（fallback 候选） |

共享语料改变「能接哪些句」，不改变 `style_profile` 统计口径。LLM prompt 中的群习惯应来自 `compile_group_style_*`，而非远程语料池。

## 语言层待实现能力

| 能力 | 说明 | 阶段 |
| --- | --- | --- |
| `compile_persona_prompt` | 合并牛格、`compile_group_style_prompt`、帕拉斯基础 system | P1 · **已交付** |
| LLM 运行时 | 主仓 `features/llm` → **AI 仓**统一 Chat API | P2 · **已交付** |
| 会话记忆 | 群 / 用户双层存储、滑动窗口、TTL；分片共享 PG | P3 · 部分（可选 `LLM_SESSION_ENABLED`） |
| 治理 | 每 bot/群开关、CD、异步队列、token 预算、`SlowPathTimer` 观测 | P4 · 部分（`LLM_GOVERNANCE_ENABLED` 等） |
| repeater fallback | 语料 miss → 异步 LLM 生成 | P5 · **骨架**（`LLM_FALLBACK_ENABLED`，默认关） |
| repeater polish | 语料 hit → 异步轻改写；失败回退原句 | P6 · **骨架**（`LLM_POLISH_ENABLED`，默认关） |

配置统一走 `pallas.toml` + WebUI（见 [settings-storage](settings-storage.md)），LLM 业务放 `src/features/llm/`，插件只负责触发与发送。

### 全局 LLM 配置键（主仓）

**`LLM_CHAT_ENABLED=true`** 时酒后 `chat`、随时 @ `llm_chat`、repeater 挂钩共用总闸。遗留 **`CHAT_ENABLE`** 仅在未显式配置 `LLM_CHAT_ENABLED` 时启用酒后 RWKV。

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_CHAT_ENABLED` | `false` | LLM 闲聊与接话 LLM **总闸**（唯一需显式打开） |
| `LLM_REPEATER_MODE` | `both` | repeater 接话 LLM：`off` / `fallback` / `polish` / `both` |
| `LLM_FALLBACK_ENABLED` / `LLM_POLISH_ENABLED` | `true` | **遗留**，未设 `LLM_REPEATER_MODE` 时仍可读 |
| `AI_SERVER_HOST` / `AI_SERVER_PORT` | `127.0.0.1:9099` | Pallas-Bot-AI 地址 |
| `LLM_GOVERNANCE_ENABLED` | `true` | 闲聊 CD / 并发 / 字符预算 |
| `LLM_SESSION_ENABLED` | `true` | 多轮会话存储 |
| `LLM_TOOLS_ENABLED` | `true` | LLM 注入方舟等 tool schema（总闸关时无效） |
| `ARKNIGHTS_KB_ENABLED` | `true` | 方舟干员结构化查询 |

遗留 `LLM_CHAT_ENABLE` / `OLLAMA_ENABLE` 仍可读为 LLM 总闸；`CHAT_ENABLE` 仅遗留酒后 RWKV。新用户优先配 `LLM_CHAT_ENABLED`。

联调（Bot 侧脚本，AI 需 `LLM_CHAT_ENABLED=true` 且 worker 在跑）：

```bash
uv run python tools/integration_llm_chat.py --ai-port 9199
uv run python tools/integration_repeater_llm.py --scenario both --ai-port 9199
```

## 本仓已有可对齐的实现

实现新能力时优先复用下列模块，避免在插件内重复造轮子：

| 待实现能力 | 可对齐的本仓模块 | 说明 |
| --- | --- | --- |
| P2 provider / HTTP | [pallas-ai-service](pallas-ai-service.md)、`plugins/llm_chat/` | 经 AI 仓 `/api/v1/chat/completions` |
| P3 会话存储 | `src/features/llm/session_store.py` | PG；可选 `LLM_SESSION_ENABLED` |
| P4 CD / 限流 | `src/features/llm/governance.py`、`command_limits/` | 闲聊治理；repeater 仍用群 CD |
| P4 慢路径观测 | `src/platform/observability/SlowPathTimer` | repeater / ingress 已在用 |
| P4 配置热重载 | WebUI + `get_llm_config()` | `features/llm/config.py` |
| P5–P6 repeater 挂钩 | `src/plugins/repeater/__init__.py`、`features/llm/fallback.py`、`polish.py` | miss / hit 分支异步提交；callback `task_type=repeater_polish` |
| P7 WebUI | `src/plugins/pb_webui/extended_api.py` | bot/group 配置 PATCH 与 cmd_perm 同路径 |
| P9 工具 metadata | `src/features/cmd_perm/`、`PluginMetadata.extra` | 与 `command_permissions` 类似声明 `llm_tools` |
| P9 游戏 tools | [arknights-knowledge-mcp](arknights-knowledge-mcp.md) | `domain/arknights` + tool registry |
| 分片 | [bot_process_sharding](bot_process_sharding.md)、`command_limits` hub | 会话共享 DB；调用收敛到 claim worker 或 hub |
| 入站路由 | [central-ingress-dispatch](central-ingress-dispatch.md) | LLM 主动回复若接入，走 ingress lane 约定 |
| 权限 | `src/features/cmd_perm/` | LLM 口令 / tool 触发绑定可配置等级 |
| 帕拉斯 system 文案 | `src/plugins/ollama/system_prompt.txt`、`prompts.py` | P1 可与 `compile_persona_prompt` 合并演进 |

## 建议 PR 顺序

```mermaid
flowchart TB
    subgraph done["已交付"]
        D1[persona 自动派生 + 群风格]
        D2[chaos 选句 + compile_group_style]
    end

    subgraph phase1["Phase 1 · 基础设施"]
        P1["compile_persona_prompt"]
        P2["features/llm → AI 仓"]
        P3["会话存储 (bot, group, user)"]
        P4["CD / 队列 / 限流"]
    end

    subgraph phase2["Phase 2 · repeater 挂钩"]
        P5["fallback: 语料 miss → LLM"]
        P6["polish: 选中句轻改写"]
    end

    subgraph phase3["Phase 3 · 可后置"]
        P7[WebUI LLM 配置与消耗]
        P8[embedding 长期记忆]
        P9["MCP / Function Calling\n见 arknights-knowledge-mcp"]
        P10[MoE / 视觉 / 联网]
    end

    done --> P1 --> P2 --> P3 --> P4 --> P5 --> P6
    P2 --> P7
    P3 --> P8
    P4 --> P9
```

| 阶段 | 交付物 | 默认 |
| --- | --- | --- |
| P1 | `compile_persona_prompt(bot_id, group_id)`：合并牛格 + `compile_group_style_prompt` + 帕拉斯基础 system | — |
| P2 | `src/features/llm/`：调用 **AI 仓统一 LLM API**（见 [pallas-ai-service](pallas-ai-service.md)）；主仓不直连 Ollama | 关 |
| P3 | PG 会话：群窗口 N 条 + 可选用户 TTL；分片 worker 共享读 | — |
| P4 | 每 bot/群开关、CD、异步队列、token 预算 | 关 |
| P5 | `_context_find` miss 且开关开 → LLM 生成 | **关** · 骨架 |
| P6 | 已有候选句 → LLM 轻改写；失败回退原句 | **关** · 骨架 |
| P7+ | WebUI、embedding、工具调用、MoE 等 | 关 |

游戏资料查询与 MCP 工具详见 [arknights-knowledge-mcp](arknights-knowledge-mcp.md)（**K1–K5** 与 P9 对齐；建议先做结构化 KB，再接 LLM tools）。

## 架构约束（实现时必须满足）

1. **不挡热路径**：learn、ingress claim、语料检索先完成；LLM 在 miss 分支或后台 worker 异步执行。
2. **默认关**：`llm_fallback_enabled`、`llm_polish_enabled` 与 repeater `fanout_enabled` 同理，WebUI 可配。
3. **分片**：配置与会话走共享 DB；LLM 调用在 claim 成功 worker 执行，或经 hub 聚合（类似 `command_limits`）。
4. **活动局**：`activity_gate` 对 LLM 路径同样降噪；跟复读不受影响。
5. **配置落盘**：新项写入 `pallas.toml` / `webui.json`，不往根目录 `.env` 扩 Bot 主配置键（见 [settings-storage](settings-storage.md)）。
6. **失败回退**：LLM 超时 / 错误 → 保持现网 repeater 行为（无回复或原句）。

## 与现有模块的接入点

| 模块 | LLM 相关扩展 |
| --- | --- |
| `src/features/persona/` | `compile_persona_prompt`；复用 `compile_group_style_snapshot` |
| `src/features/llm/` | Chat 客户端、fallback/polish、会话 CRUD |
| `Pallas-Bot-AI`（**并行仓库**） | 统一 LLM 网关、会话、provider；见 [pallas-ai-service](pallas-ai-service.md) |
| `src/plugins/repeater/__init__.py` | fallback / polish 钩子（默认关） |
| `src/platform/ingress/` | 可选：LLM 主动回复决策（后期） |
| `src/plugins/pb_webui/extended_api.py` | LLM 配置、只读 `style_profile` 展示 |
| `src/plugins/dream/` | 与 LLM 并存；dream 仍为非 LLM 漂移，不混用会话 |
| `src/domain/arknights/` | 游戏结构化数据；见 [arknights-knowledge-mcp](arknights-knowledge-mcp.md) |
| `src/features/llm/tools/`（新建） | Tool registry；MCP 与 `ollama` 共用 |
| `src/features/message_scrub/` | P2 provider 链参考实现 |
| `src/features/command_limits/` | P4 CD；分片 hub 聚合参考 |
| `src/plugins/llm_chat/` | 随时 @ 闲聊；4.0 经 `features/llm` |
| `src/features/cmd_perm/` | P9 `llm_tools` 声明与 WebUI 权限覆盖 |

## 验收清单

### 当前阶段（persona，无 LLM）

- [x] 群风格 dirty 刷新 + `style_profile` 写库
- [x] `resolve_persona` 合并群画像；`chaos_bias` 参与选句
- [x] `compile_group_style_snapshot` / `compile_group_style_prompt` 契约稳定
- [x] WebUI 只读展示 `style_profile`（群配置弹窗 + `style_profile_snapshot`）

### LLM 基础设施（P1–P4）

- [x] `compile_persona_prompt` 输出可人工 review
- [x] staging 固定 prompt 调通 Chat API（`tools/integration_llm_chat.py`）
- [ ] 分片多 worker 会话读写无重复回复
- [ ] 高并发下 CD/队列不打爆 PG 池与 API 配额

### LLM 行为（P5–P6）

- [x] fallback 骨架：语料 miss 可异步提交；关：与现网一致
- [x] polish 骨架：命中语料可异步轻改写；AI 失败 callback 回退原句
- [ ] polish 开：句长/语气贴近群 `length_pref`（待 prompt 迭代）
- [ ] 与 fanout、shard、`group_style_enabled=false` 组合无回归

## 相关文档

- [persona-reply-style.md](persona-reply-style.md) — 行为层总览
- [group-style-persona.md](group-style-persona.md) — 群统计与刷新
- [common-layers.md](common-layers.md) — `features/` 分层
- [control-plane-corpus-federation.md](control-plane-corpus-federation.md) — 共享语料读写
- [arknights-knowledge-mcp.md](arknights-knowledge-mcp.md) — 明日方舟 KB 与 MCP 工具
- [pallas-ai-service.md](pallas-ai-service.md) — Bot ↔ AI 仓 4.0 协同
