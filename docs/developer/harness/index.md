# 工程化地图（Harness Index）

本页是「智能体如何导航与验证 Pallas-Bot」的入口地图，只做定位，不重复正文。每份文档声明 **owner**（负责保持新鲜度的人）与 **验证状态**（该页描述的行为如何被机器检查）。

**Owner 约定**：`platform` 表示内核平台维护者，`llm` 表示 LLM/Agent 产品维护者，`webui` 表示 WebUI 维护者，`plugin` 表示内置/官方插件维护者。维护者在合入架构/能力变更时必须同步对应文档（见 [架构总览](/developer/architecture/overview)）。

**验证状态约定**：`manual`（人工核对）、`lint`（Ruff/结构检查）、`unit`（pytest）、`ci`（CI 门禁，见 `.github/workflows/ci.yml`）。带 `code:` 的条目指可直接定位的代码锚点。

## 领域边界

| 主题 | 文档 | Owner | 验证状态 |
| --- | --- | --- | --- |
| 多仓分工、层职责、归属判定 | [architecture/overview](/developer/architecture/overview) | platform | manual · code:`pallas/` |
| Core vs 扩展 | [architecture/core-vs-extensions](/developer/architecture/core-vs-extensions) | platform | manual |
| 仓库布局 | [reference/repo-layout](/developer/reference/repo-layout) | platform | manual |
| 插件治理 | [architecture/plugin-governance](/developer/architecture/plugin-governance) | plugin | manual |

## 消息链路与运行时

| 主题 | 文档 | Owner | 验证状态 |
| --- | --- | --- | --- |
| 统一消息入口（direct/matcher） | [architecture/message-runtime](/developer/architecture/message-runtime) | platform | unit · code:`pallas/core/platform/message_runtime/`、`pallas/core/platform/ingress/` |
| 分片运行时 | [architecture/shard-runtime](/developer/architecture/shard-runtime) | platform | unit · code:`pallas/core/platform/shard/` |
| 多牛协作 | [architecture/multi-bot-collaboration](/developer/architecture/multi-bot-collaboration) | platform | unit |
| 后台任务与 work aux | [maintainer/deploy/single-process](/maintainer/deploy/single-process) | platform | unit |

## LLM 与 Agent

| 主题 | 文档 | Owner | 验证状态 |
| --- | --- | --- | --- |
| Agent 生命周期（入口/上下文/工具/投递） | [architecture/agent-lifecycle](/developer/architecture/agent-lifecycle) | llm | unit · code:`pallas/product/llm/`、`packages/llm_chat/` |
| 上下文注入全景 | [architecture/llm-context-injection](/developer/architecture/llm-context-injection) | llm | unit |
| 输出路径与护栏 | [architecture/llm-output-path](/developer/architecture/llm-output-path) · [llm-output-guardrails](/developer/architecture/llm-output-guardrails) | llm | unit |
| 群洞察与风格 | [architecture/group-insight-semantic-style](/developer/architecture/group-insight-semantic-style) | llm | unit |

## 配置 / 观测 / 事件日志

| 主题 | 文档 | Owner | 验证状态 |
| --- | --- | --- | --- |
| 配置存储（`pallas.toml`/`webui.json`） | [architecture/config-storage](/developer/architecture/config-storage) | platform | unit · 结构检查 `tools/check_*` |
| 插件业务事件日志 | [architecture/plugin-event-logging](/developer/architecture/plugin-event-logging) | plugin | manual |
| 日志/指标/trace 排障入口 | [maintainer/operate/logs](/maintainer/operate/logs) · [troubleshooting](/maintainer/operate/troubleshooting) | platform | manual |

## 工具 / 测试 / CI

| 主题 | 位置 | Owner | 验证状态 |
| --- | --- | --- | --- |
| 事件级行为实验工具 | `tools/llm_event_harness.py` | llm | unit · `tests/tools/test_llm_event_harness*.py` |
| 行为实验方法与契约 | [harness/behavior-lab](/developer/harness/behavior-lab) | llm | unit |
| 跨进程运行态观测（脱敏快照/查询/TTL） | `tools/observe_runtime.py` | platform | unit · `tests/tools/test_observe_runtime.py` |
| 浏览器级 UI 验收（CDP 驱动 headless chromium） | `tools/browser_acceptance.py` | webui | unit · `tests/tools/test_browser_acceptance.py` |
| 结构检查脚本 | `tools/check_plugin_imports.py`、`check_console_openapi_drift.py` 等 | platform | ci · `tools/check_*` |
| 文档链接/锚点检查（doc-gardening） | `tools/check_doc_links.py` | platform | ci · `tools/check_*` |
| fixture 健康扫描 | `tools/check_fixture_health.py` | llm | ci · `tools/check_*` |
| 黄金原则扫描（地图链接/owner/验证状态） | `tools/check_golden_principles.py` | platform | ci · `tools/check_*` |
| 自动 PR loop（治理漂移→修复 PR，保留人工审批） | `tools/auto_pr_loop.py` | platform | unit · `tests/tools/test_auto_pr_loop.py` |
| CI 门禁（Ruff/import/矩阵/OpenAPI/构建） | `.github/workflows/ci.yml` | platform | ci |
| 健康/启动检查与容器健康 | `.github/workflows/health-check.yml` | platform | ci · `uv run pallas status` |
| 回归测试目录 | `tests/api/runtime/`、`tests/platform/message_runtime/`、`tests/product/llm/` | platform | unit |

## 数据边界（敏感字段默认不入长期产物）

| 约定 | Owner | 验证状态 |
| --- | --- | --- |
| 脱敏 fixture 与稳定 JSON 结果（`redaction_summary`） | llm | unit · [behavior-lab](/developer/harness/behavior-lab) |
| 密钥/本地配置不入库 | platform | manual · `pre-commit` |
| 日志正文不暴露消息正文 | platform | manual · 日志规范（根 `AGENTS.md`） |

## 约定速查

| 区 | 约定 |
| --- | --- |
| 代码风格/质量门禁 | Ruff；作用域 `pallas/`、`packages/`（见根 `AGENTS.md`） |
| 日志 | loguru 风格 `{}` 占位；高频英文叙事、低频运维中文叙事 |
| 提交 | `type(scope): 中文短句`；一个 PR 一类问题 |
| 新增架构/能力文档 | 必须同步本页 owner/验证状态 + `tools/scripts/sync_docs_to_web.py` 的 `FILE_MAP` |
