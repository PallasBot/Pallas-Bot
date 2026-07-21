# Changelog

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

[4.0.3]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.2...v4.0.3
[4.0.2]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.1...v4.0.2
[4.0.1]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.0...v4.0.1
[4.0.0]: https://github.com/PallasBot/Pallas-Bot/compare/v3.9.3...v4.0.0
