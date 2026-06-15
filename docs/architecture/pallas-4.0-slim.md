# Pallas-Bot 4.0 · 本体瘦身与插件分家

> **目标版本：4.0** · **开发分支：`feat/4.0-slim`** · 合流目标：**`dev`**  
> 4.0 总览（含牛格轨道）见 [pallas-4.0-roadmap](pallas-4.0-roadmap.md)（`dev` 合流后与本文件同仓维护）。牛格 / LLM / AI 仓 **不在本文范围**。

## 目标

| 做 | 不做 |
| --- | --- |
| 缩小默认安装与 Docker 镜像 | 改动 persona / LLM / repeater 接话逻辑 |
| 玩法与重依赖插件迁出官方扩展包 | 在本分支实现方舟 KB 或 AI 仓 API |
| 明确 core / extra / local 加载与 WebUI 展示 | 一次性拆完所有历史插件（分 PR 迁移） |
| 3.x → 4.0 迁移文档与 optional `uv` extras | 破坏 `local/plugins` 覆盖能力 |

瘦身完成后：**不装扩展包** 仍可运行系统插件 + **repeater（含牛格）**；缺扩展包时对应命令/help 项明确不可用而非静默失败。

## 设计参照

| 参照 | 对齐点 |
| --- | --- |
| [GsUID Core](https://github.com/Genshin-bots/gsuid_core) | 核心仓 + 插件仓；控制台管配置与插件 |
| [绪山真寻 Bot](https://github.com/zhenxun-org/zhenxun_bot) | 本体仅核心；[独立插件仓库](https://github.com/zhenxun-org/zhenxun_bot_plugins) + 插件索引 |

Pallas 已有机制（4.0 强化而非重造）：

- [site-customization-and-updates.md](site-customization-and-updates.md) — `local/plugins`、`extra_plugin_dirs`
- [plugin-convention.md](plugin-convention.md) — 插件目录约定
- [bot_process_sharding.md](bot_process_sharding.md) — hub/worker 一致加载
- **[Pallas-Bot-WebUI](https://github.com/PallasBot/Pallas-Bot-WebUI)** — **`feat/4.0`** 分支承接控制台改造

## 本体 vs 扩展边界

### 保留在本体 `src/plugins/`（core）

| 插件 | 类别 |
| --- | --- |
| `repeater` | 核心接话（牛格由 persona 分支交付） |
| `help` | 帮助与插件发现 |
| `pallas_webui` | 控制台 API |
| `pallas_protocol` | 协议端管理 |
| `ingress_gate` | 入站配套 |
| `bot_status` | 在线与通知 |
| `callback` | 异步回调 |
| `request_handler` | 审批 |
| `blacklist` / `block` | 安全 |
| `pallas_console_metrics` | 指标 |
| `relogin_bot` / `relogin_forward` | 账号运维 |
| `connectivity` | 轻量探针（依赖仍轻则保留；否则降为扩展） |

### 迁出本体（官方扩展包）

| 当前插件 | 建议包名 | 依赖特征 | 优先级 |
| --- | --- | --- | --- |
| `duel` | `pallas-plugin-duel` | 玩法 + `domain/arknights` | P0 |
| `who_is_spy` | `pallas-plugin-who-is-spy` | 玩法 + 协调存储 | P0 |
| `roulette` / `drink` | `pallas-plugin-party` 或拆分 | 轻玩法 | P1 |
| `dream` | `pallas-plugin-dream` | repeater 旁路 | P1 |
| `maa` / `maa_hub` | `pallas-plugin-maa` | 远控、HTTP | P0 |
| `draw` | `pallas-plugin-draw` | 图像 API | P1 |
| `sing` / `chat` | `pallas-plugin-ai-media` | AI 仓媒体 | P1 |
| `greeting` / `take_name` | `pallas-plugin-social` | 体验 | P2 |
| `community_stats` | 扩展或保留 core | 上报；产品决策 | P2 |

**留内核、不随插件迁出**：`src/domain/arknights/`、`src/features/*` 公开 API、分片与 ingress。

### 加载优先级

```mermaid
flowchart TB
    LOCAL["local/plugins"]
    EXTRA["官方扩展包"]
    CORE["本体 core"]

    LOCAL --> NB["NoneBot 插件表"]
    EXTRA --> NB
    CORE --> NB
```

1. `local/plugins` 同名 override 扩展与 core
2. 扩展包 `pyproject` 依赖 `pallas-bot`
3. core 仅在本体 `src/plugins/` 维护

实现触点：`read_bootstrap_extra_plugin_dirs()`、`src/platform/bot_runtime/plugin_loader.py`、`help` 插件列表来源标注。

## 依赖与安装面（S2）

### optional extras（目标）

```toml
[project.optional-dependencies]
plugins-duel = ["pallas-plugin-duel>=4.0"]
plugins-maa = ["pallas-plugin-maa>=4.0"]
plugins-game = ["pallas-plugin-duel", "pallas-plugin-who-is-spy"]
deploy-full = ["pallas-bot[plugins-game,plugins-maa,...]"]
```

默认 `uv sync` 仅 core 依赖；全功能部署用 `--extra deploy-full`。

## Docker 与 CI（S3）

| 项 | 4.0 目标 |
| --- | --- |
| 默认镜像 | core + repeater；体积较 3.x 减小 |
| compose profile | 预装常用扩展 |
| 本体 CI | 仅 core 插件测试 |
| 扩展仓 CI | 独立；可选 nightly 对 `dev` e2e |

分片：hub/worker 相同 extras / `extra_plugin_dirs`。

## WebUI 协同（`feat/4.0`）

| 项 | 说明 |
| --- | --- |
| 插件列表 | 展示 core / extra / local 来源 |
| 扩展说明 | 推荐 extras、迁移对照表 |
| 主仓 API | `pallas_webui` 返回插件 `source` 字段 |

## 实施阶段

| 阶段 | 交付 |
| --- | --- |
| **S1** | 本文 + 矩阵冻结；扩展仓模板 |
| **S2** | duel/maa 等首包迁出 |
| **S3** | pyproject extras |
| **S4** | Docker / CI 分轨 |
| **S5** | 迁移文档 + WebUI API |

## 3.x → 4.0 迁移（摘要）

1. 升级本体 4.0.0  
2. 按对照表 `uv sync --extra …`  
3. `local/plugins` 不变  
4. 分片各 worker 相同扩展集  
5. 未装扩展：help 不展示；触发时提示安装扩展包  

## 验收清单

- [ ] 默认 `uv sync` 后仅 core 插件树
- [ ] `--extra plugins-duel` 后 duel 可用
- [ ] 未装扩展时 help/命令行为符合文档
- [ ] 分片 hub/worker 扩展一致
- [ ] 默认 Docker 镜像无迁出插件代码
- [ ] WebUI feat/4.0 可展示插件 source（或 API 就绪）
- [ ] 迁移文档完整

## 相关文档

- [4.0-development.md](../develop/4.0-development.md) — 分支约定（合流后）
- [site-customization-and-updates.md](site-customization-and-updates.md)
- [plugin-convention.md](plugin-convention.md)
- [bot_process_sharding.md](bot_process_sharding.md)
