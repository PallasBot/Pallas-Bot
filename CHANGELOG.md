# Changelog

## [4.1.6] - 2026-07-26

本版相对 4.1.5：发言感知（别名提及 / 氛围插嘴 / 续聊软窗）配置进 WebUI 对话策略。捆绑 WebUI **v0.7.12**（发版前需先合并并发布该 WebUI tag）。

### Added

- WebUI 暴露 `LLM_SPEAK_*` 发言感知开关与细调（总闸、别名提及、ambient、续聊软窗）

## [4.1.5] - 2026-07-26

本版相对 4.1.4：社交型 Agent 平台（观察队列 / 人物事实 / 口癖 / 任务编排）、LLM 动作与开口拆分、联网搜索与 Draw 连通修复；重复器接话 stage 收敛。捆绑 WebUI **v0.7.11**（人物 / 任务观测与口癖审批等；发版前需先发布该 WebUI tag）。

### Added

#### Agent 平台与记忆

- 记忆观察队列、Planner 与 lifecycle 检索
- 人物事实、跨群同意与群体画像
- 账号口癖候选库；成功回复抽短习惯后审批注入人设（非整句接话）
- 行动工具、任务编排与 Agent Platform 控制台 API
- 请求级 usage 账本与历史脏数据过滤

#### LLM 对话与工具

- 动作与开口拆分：工具结果经 `chat.reply` 发可见对白；可短 ack 或沉默
- 硬域未命中时按 hints / 描述软召回工具；记住已激活工具并补全追踪
- 统一重复器能力解析与阶段规划；复用聊天上下文与工具组装
- 嵌入检索能力映射；回退时停用语义检索

#### 文档

- 全站信息架构与社区投稿墙；AI 观测 / 联网搜索说明；Agent 架构与部署边界

### Fixed

- 联网搜索可正确选中并支持配置（含 Tavily 等）
- Draw 适配移除 `runtime_mode` 后的连通探测
- AI 口令派发透传原消息图 / @ 素材，并排除唤醒 @bot
- 压制动作后 `chat.reply` 元叙述废话

### Changed

- 收敛 LLM 接话 stage 与 lite 默认策略；移除旧 LLM 提交路径
- 文案「闲聊」改为「LLM 对话」；兼容会话档位标注 deprecated
- 发行捆绑控制台取 WebUI **v0.7.11**

## [4.1.4] - 2026-07-26

本版相对 4.1.3：数据库韧性与 Mongo→PG 迁移、口令工具多域召回与选型调试、同伴身份与输出闸、LLM 日级观测计数；控制台配套健康/后端切换与异步更新。捆绑 WebUI **v0.7.9**（迁移向导、可搜索 Combobox、工具选型预览等）。

### Added

#### 数据库

- 健康状态与热路径非关键门禁；低优先级写队列与 schema 步骤可观测
- 版本化 schema 注册；Mongo→PostgreSQL 控制台迁移任务（含热重绑尝试）
- 控制台：数据库健康与表白名单只读 API；后端切换与连通性探测

#### 口令工具与闲聊（LLM）

- 多域结构召回与工具选型打分；`tools.find` 全量回退检索
- 工具选型预览与 hints / 描述覆盖 API（控制台可调试口语选型）
- 插件工具声明式触发说法与口语召回；点歌等域收窄，避免 command 全家桶
- 同伴牛牛身份注入；输出旁白 / 填料闸
- `reply_gate` / 发言感知 / 选择性回复 / 工具链路日级观测计数

#### 控制台与插件

- 「应用 Bot 更新」改为异步 job，并上报真实进度百分比
- 插件配置 `ui_group` 分组（如 repeater / webui / help）

#### 捆绑控制台（WebUI v0.7.9）

- Mongo→PostgreSQL 迁移向导；数据库健康摘要与表白名单只读浏览
- Bot / 长列表选择改为可搜索 Combobox（≥8 显示搜索）；AI 观测群可搜可选
- 对话工具页：口语选型预览与 hints / 描述覆盖
- 工具条与配置弹窗体验（右钉操作、存储视图切换、群好友配置删除等）

### Fixed

- DeepSeek thinking 默认关闭，并正确回传 `reasoning_content`
- 口令工具回传歌名等结果字段
- 动态加载迁移脚本时先注册 `sys.modules`，避免重复导入失败
- SPA HTML 入口禁用长期缓存，降低发版后仍引用旧 hash 资源的概率
- 精简数据库后端探测与保存文案

### Changed

- 同步控制台 OpenAPI（迁移任务、工具预览与覆盖、数据库健康等）
- 发行捆绑控制台默认取 WebUI 最新 tag（本版 **v0.7.9**）

## [4.1.3] - 2026-07-25

### Changed

- 帮助总览菜单改为三列布局，并按版心收窄卡片与字号

## [4.1.2] - 2026-07-25

本版相对 4.1.1：闲聊更会「接话 / 认人 / 调工具」，控制台补齐工具与语料调试能力；捆绑 WebUI **v0.7.8**。

### Added

#### 闲聊与人设

- 群聊发言感知：别名提及、ambient 插嘴；硬触发后软窗口续聊
- 关系层：弱观察沉淀、人对语气偏置、称呼注入；登录昵称自称与 `self_aliases`
- 单群表达库接入牛格 / 情感装配；强场景接话双预算与反哺写回
- 会话工具轨迹 `tool_trace`（便于排障与历史回看）

#### 口令工具（LLM Tools）

- 插件可通过 `extra["llm_tools"]` 声明群口令工具；按话术 select 域注入
- 内置 / 官方扩展陆续开放（喝酒、帮助、轮盘、唱歌、画画等）；工具名兼容 DeepSeek 等 provider

#### 控制台 API

- LLM 工具只读清单；语料源详情 / chunk 预览 / 检索试探
- `provider_gateway` 主备线路声明；活跃群 DAG/MAG 与 AI 费用补齐
- 社区投稿墙代理 API

#### 其他

- 帮助图 v4 分组，插件 `help_tag` 覆盖

### Fixed

- 酒后对话启动加载；硬触发空回复兜底（避免已读不回）
- Provider 工具名去点号；thinking 与 `tool_choice=required` 冲突
- 检索降噪（memory/knowledge `min_score` 与查询门控）；表达回灌限频、抑制开场复读
- 僵尸 WS 隔离，避免假在线挡重新上号；ingress 预筛允许「命令+紧贴参数」
- 社区投稿：固定正式中心、可不选 Bot、默认昵称

### Changed

- 发行捆绑控制台默认取 WebUI 最新 tag（本版 **v0.7.8**）
- 官方扩展仓库迁至 `PallasBot/Plugin-*`

## [4.1.1] - 2026-07-24

### Fixed

- LLM：修复酒后对话因 `Bot` 仅在 TYPE_CHECKING 导入导致启动 NameError

## [4.1.0] - 2026-07-24

### Added

- LLM：内核直连 Provider / ops（模型管理、会话与指标），不再依赖 AI 仓中转
- LLM：记忆图谱（entity/edge）与 mid-term / session ops
- WebUI：LLM ops 与记忆图 API；发版从 WebUI 仓库根构建 React

### Changed

- AI Runtime / 文档：LLM 能力以 Bot 内核为准；AI 仓侧重媒体（唱歌 / TTS）
- Release：兼容 WebUI 根目录与旧 `react/` 子目录构建路径

### Removed

- 遗留登录页 HTML（`login_page.py`）及对应测试

## [4.0.3] - 2026-07-21

### Fixed

- LLM：Provider 模型列表改由 Bot 直连上游（不再经 AI 中转）
- CQ 段字段转义兼容 int，避免撤回等链路因 `at.qq` 等为整型而报错
- 分片日志：按 worker 隔离 traceback 合并；理清更新检查缓存兜底日志
- Docs 同步：补齐 VitePress 链接变换，避免 Docs CI 死链
- 同步控制台 OpenAPI，补齐 LLM Provider 模型发现接口

### 文档

- 补充社区插件发版后同步索引的步骤

## [4.0.2] - 2026-07-21

### Added

- LLM：结构化回复 PASS 与接话必要性门控，减少垫话与元问题胡编
- LLM：场景口气、注意力漂移约束；接话轻润色改用口语 expressor
- LLM：情境规则关键词热注入；反馈样本 BAD/OK 对照 few-shot
- LLM：可选错别字拆条、表情 fit 与回复效果评审
- LLM：`session_store` / 群记忆 / 关系便签支持 Mongo 后端

### Fixed

- LLM：Mongo 记忆与关系 ID 原子分配，并缓存 session 后端选择
- LLM：收紧接话门控，拦截垫词与元问题胡编

### Changed

- LLM：闭嘴关键词收敛到 `shut_up` 共用定义
- 同步控制台 OpenAPI；预提交可自动导出并联动 WebUI 类型

### 文档

- 补充 OpenAPI 双仓同步说明
- Release / 构建脚本：WebUI 解压路径改为 `data/pb_webui`，完善发版说明

## [4.0.1] - 2026-07-20

### Added

- Git 镜像：支持 GitHub 镜像源，并在控制台可配置
- 社区中心：WebUI 连通检测 API（含 OpenAPI 导出）
- WebUI BFF：媒体模型与 LLM 配置分家；Git 镜像相关增强
- AI Runtime 总览：上报画画 `draw_runtime_mode`（区分插件直通与 AI 绘图队列）

### Fixed

- 语料贡献时强制 re-enroll，避免贡献后未重新入队
- WebUI 启动时预创建并挂载 `store-assets`，避免官方插件封面被 SPA catch-all 当成 HTML
- AI 扩展默认健康路径改为 `/health`
- WebUI 保存 Literal 数字枚举时，字符串（如 `"1800"`）coerce 为 int，避免 400
- docs 分支 CI：改为 tip 镜像，避免反复 merge 分叉

### Changed

- 同步控制台 OpenAPI（含 git-mirror 等）

### 文档

- README 补充 Notion 牛牛协作区邀请链接
- 修正 Pallas-Bot-AI 外链分支为 `master`

## [4.0.0] - 2026-07-19

### Added

- 内核目录 `pallas/` + 内置插件 `packages/`；移除历史 `src/` 布局
- 稳定扩展入口 `pallas.api.*`（commands / config / perm / limits / metadata / paths / storage 等）
- `pallas-core` PyPI 包（`scripts/build_core.sh`；tag `v*` 触发 `.github/workflows/publish-pypi-core.yml`）
- 官方插件安装：`uv run pallas ext install`、控制台插件商店
- 配置合并：`config/pallas.toml` + `data/pallas_config/webui.json`（WebUI 落盘优先）
- 首次 Setup Wizard、AI 配置体检向导（WebUI）
- OpenAPI 导出 `openspec/pallas-console-v1.json` 与 WebUI codegen 客户端
- LLM capability 信封统一；AI runtime health 单一事实源（插件熔断去重）
- AI Runtime 总览页 `/ai/runtime`
- 插件治理工作区（权限 / 冷却 / 运行开关同屏）
- `PALLAS_DUPLICATE_PREFIX_STRICT` 生产门禁（重复前缀）

### Changed

- 默认仅加载 **core 插件**；玩法 / 协议 / AI 媒体等改 **官方插件**（pip）
- 智能接话依赖 **Pallas-Bot-AI 4.0+**；`CHAT_ENABLE` / `OLLAMA_*` → `LLM_*`（见 [ollama 迁移](docs/guide/llm-migrate-from-ollama.md)）
- WebUI 窄屏断点 ≤560px 规范（cmd 矩阵、插件配置、商店等）

### Removed

- 3.x 内置玩法插件直载（需安装对应 `pallas-plugin-*` 扩展）
- 插件侧自建 AI circuit 回退（改读 `pallas.api.ai_runtime_health`）

### 升级

见 [4.0 启动说明](docs/guide/4.0-start.md) 与 [4.0 迁移指南](docs/guide/4.0-migration.md)。

[4.1.6]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.5...v4.1.6
[4.1.5]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.4...v4.1.5
[4.1.4]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.3...v4.1.4
[4.1.3]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.2...v4.1.3
[4.1.2]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.1...v4.1.2
[4.1.1]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.0...v4.1.1
[4.1.0]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.3...v4.1.0
[4.0.3]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.2...v4.0.3
[4.0.2]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.1...v4.0.2
[4.0.1]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.0...v4.0.1
[4.0.0]: https://github.com/PallasBot/Pallas-Bot/compare/v3.9.3...v4.0.0
